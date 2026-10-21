"""Arma todas las piezas.

    python -m hello_assistant                     modo voz (normal)
    python -m hello_assistant --texto             modo texto (para probar sin micrófono)
    python -m hello_assistant --prueba-activacion solo cuenta activaciones (prueba de falsos positivos)
    python -m hello_assistant --microfonos        lista los micrófonos disponibles
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from . import config as cfg
from .brain import Cerebro
from .keep_awake import MantenerDespierta
from .music_index import IndiceMusica
from .player import Reproductor
from .timers import Temporizador, Temporizadores, formatear_duracion
from .tools import Herramientas

log = logging.getLogger("hello_assistant")


class App:
    def __init__(self, config: cfg.Config) -> None:
        self.config = config
        self.despierta = MantenerDespierta()
        self.indice = IndiceMusica(config.carpetas_musica)
        self.reproductor = Reproductor(config.mpv_ruta, config.mostrar_video)
        self.temporizadores = Temporizadores(self._al_terminar_temporizador)
        self.herramientas = Herramientas(self.indice, self.reproductor, self.temporizadores)
        self.cerebro = Cerebro(config, self.herramientas)
        self.hablante = None  # se crea en modo voz
        self.escucha = None

    def decir(self, texto: str) -> None:
        if self.hablante:
            self.hablante.decir(texto)
        else:
            print(f"\n🗣  {texto}\n", flush=True)

    def _al_terminar_temporizador(self, t: Temporizador) -> None:
        nombre = f" de {t.etiqueta}" if t.etiqueta else ""
        texto = f"Terminó el temporizador{nombre}, de {formatear_duracion(t.duracion)}."
        if not self.hablante:
            print("\a", end="", flush=True)
            self.decir(texto)
            return
        self._bajar_musica()
        try:
            self.hablante.sonido("alarma")
            self.hablante.decir(texto)
        finally:
            self.reproductor.restaurar_volumen()

    def _bajar_musica(self) -> None:
        try:
            self.reproductor.bajar_para_escuchar()
        except Exception:  # noqa: BLE001
            log.debug("No pude bajar la música", exc_info=True)

    def iniciar(self) -> None:
        if self.despierta.iniciar():
            log.info("La computadora no se va a dormir mientras la app esté abierta.")
        disponibles = self.indice.raices_disponibles(avisar=True)
        if not disponibles:
            log.warning("Ninguna carpeta de MUSICA_CARPETAS existe: la biblioteca queda vacía.")
        else:
            log.info("Indexando %d de %d carpetas.", len(disponibles), len(self.config.carpetas_musica))
        self.indice.escanear_en_segundo_plano()
        self.indice.vigilar()

    def cerrar(self) -> None:
        if self.escucha:
            self.escucha.detener()
            self.escucha.mic.detener()
        self.temporizadores.cancelar_todos()
        self.indice.detener()
        self.reproductor.cerrar()
        self.despierta.detener()

    # ---------- modos ----------
    def bucle_texto(self) -> None:
        print("Hello Assistant (modo texto). Escribí tu pedido, o 'salir'.\n")
        while True:
            try:
                texto = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if texto.lower() in {"salir", "exit", "quit"}:
                break
            if texto:
                self.decir(self.cerebro.preguntar(texto))

    def bucle_voz(self, solo_prueba: bool = False) -> None:
        from .speaker import Hablante
        from .voice import crear_escucha

        microfono = elegir_microfono(self.config.microfono)
        print("Preparando la voz (la primera vez descarga los modelos, puede tardar)...")
        self.hablante = Hablante(self.config.piper_voz, self.config.velocidad_voz)
        self.escucha = crear_escucha(
            self.config,
            microfono=microfono,
            al_pedido=self.cerebro.preguntar,
            al_activar=self._bajar_musica,
            al_terminar=self.reproductor.restaurar_volumen,
            hablante=self.hablante,
            solo_prueba=solo_prueba,
        )
        inicio = time.monotonic()
        if solo_prueba:
            print('\nPRUEBA DE ACTIVACIÓN: dejala escuchando (tele, música, charla). '
                  'Cada activación suena un "bip". Ctrl+C para terminar y ver el resumen.\n')
        else:
            print('\nListo. Decí "Hola asistente" y después tu pedido. Ctrl+C para salir.\n')
        try:
            self.escucha.bucle()
        except KeyboardInterrupt:
            pass
        finally:
            if solo_prueba:
                horas = (time.monotonic() - inicio) / 3600
                e = self.escucha.estadisticas
                print(f"\nResumen: {horas * 60:.0f} minutos escuchando, {e['segmentos']} fragmentos "
                      f"de voz, {e['paso1']} pasaron el paso 1, {e['activaciones']} activaciones.")


def _microfonos_disponibles() -> list[tuple[int, str]]:
    """Entradas de audio del sistema (sin duplicados de otras APIs de audio en Windows)."""
    import sounddevice as sd

    api = sd.default.hostapi
    return [
        (i, d["name"]) for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0 and d["hostapi"] == api
    ]


def _listar_microfonos() -> None:
    for i, nombre in _microfonos_disponibles():
        print(f"{i}: {nombre}")


def elegir_microfono(preferido: str | int | None) -> int | None:
    """Pregunta qué micrófono usar. Enter elige el marcado con *."""
    import sounddevice as sd

    opciones = _microfonos_disponibles()
    if not opciones:
        print("No encontré ninguna entrada de audio.")
        return None

    marcado = 0
    defecto_sistema = sd.default.device[0]
    for n, (i, nombre) in enumerate(opciones):
        if (isinstance(preferido, int) and i == preferido) or (
            isinstance(preferido, str) and preferido.lower() in nombre.lower()
        ):
            marcado = n
            break
        if preferido is None and i == defecto_sistema:
            marcado = n

    print("\n¿Qué micrófono querés usar?")
    for n, (_, nombre) in enumerate(opciones, start=1):
        print(f"  {'*' if n - 1 == marcado else ' '} {n}. {nombre}")
    while True:
        try:
            r = input(f"Número (Enter = {marcado + 1}): ").strip()
        except EOFError:
            r = ""
        if not r:
            elegido = opciones[marcado]
            break
        if r.isdigit() and 1 <= int(r) <= len(opciones):
            elegido = opciones[int(r) - 1]
            break
        print(f"Escribí un número del 1 al {len(opciones)}.")
    print(f"Usando: {elegido[1]}\n")
    return elegido[0]


def main() -> int:
    parser = argparse.ArgumentParser(prog="hello_assistant")
    parser.add_argument("--texto", action="store_true", help="usar por texto en vez de voz")
    parser.add_argument("--prueba-activacion", action="store_true",
                        help="solo contar activaciones, sin ejecutar pedidos")
    parser.add_argument("--microfonos", action="store_true", help="listar micrófonos")
    parser.add_argument("--debug", action="store_true", help="mostrar todo lo que transcribe")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for ruidoso in ("httpx", "httpx2", "httpcore", "openai", "faster_whisper", "urllib3"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    if args.microfonos:
        _listar_microfonos()
        return 0

    try:
        config = cfg.cargar()
    except cfg.ErrorConfig as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 1

    app = App(config)
    app.iniciar()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        if args.texto:
            app.bucle_texto()
        else:
            app.bucle_voz(solo_prueba=args.prueba_activacion)
    finally:
        app.cerrar()
    return 0
