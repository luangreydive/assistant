"""Bucle de voz: escucha continua -> frase de activación -> pedido -> respuesta.

Cada vez que el VAD detecta a alguien hablando, Vosk busca la frase EN ESTE EQUIPO (gratis).
Solo si Vosk cree escucharla, ESE fragmento se transcribe con OpenAI para confirmarla (Vosk
puede confundir, p. ej., "soy la asistente" con "hola asistente"). Si el pedido venía en la
misma frase, esa transcripción ya lo trae. Las charlas de la casa no salen del equipo.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable

import numpy as np

from .audio import BLOQUE, DUR_BLOQUE, SR, VAD, Microfono
from .config import carpeta_base
from .speaker import Hablante
from .stt import PROMPT_COMANDO, DetectorFrase, DetectorLocal, Transcriptor, a_wav

log = logging.getLogger(__name__)

SIGUE_HABLANDO = 0.8   # si empezás el pedido antes de esto tras la frase, no hay bip
UMBRAL_HABLA = 0.5      # probabilidad de voz para empezar un segmento
UMBRAL_SILENCIO = 0.35  # por debajo de esto cuenta como silencio
PRE_ROLL = 0.4          # segundos de audio previos que se agregan al segmento


class EscuchaVoz:
    def __init__(
        self,
        microfono: Microfono,
        vad: VAD,
        transcriptor: Transcriptor,
        detector: DetectorLocal,
        verificador: DetectorFrase,
        hablante: Hablante,
        al_pedido: Callable[[str], str],
        al_activar: Callable[[], None] = lambda: None,
        al_terminar: Callable[[], None] = lambda: None,
        solo_prueba: bool = False,
        duracion_minima: float = 0.6,
    ) -> None:
        self.mic = microfono
        self.vad = vad
        self.transcriptor = transcriptor
        self.duracion_minima = duracion_minima
        self.detector = detector
        self.verificador = verificador
        self.hablante = hablante
        self.al_pedido = al_pedido
        self.al_activar = al_activar
        self.al_terminar = al_terminar
        self.solo_prueba = solo_prueba
        self._parar = threading.Event()
        self._arrastre: list[np.ndarray] = []
        self.estadisticas = {"segmentos": 0, "candidatas": 0, "activaciones": 0, "enviados_openai": 0}

    def detener(self) -> None:
        self._parar.set()

    # ---------- segmentación por VAD ----------
    def _segmento(self, max_seg: float, silencio_fin: float,
                  espera_max: float | None = None) -> tuple[np.ndarray, bool] | None:
        """Junta audio desde que empieza la voz hasta un silencio. Devuelve (audio, cortado),
        donde cortado=True si se llegó a max_seg sin silencio (p. ej. con música de fondo).
        Con espera_max: devuelve None si nadie empieza a hablar en ese tiempo."""
        previo: deque[np.ndarray] = deque(maxlen=max(1, int(PRE_ROLL / DUR_BLOQUE)))
        seg: list[np.ndarray] = self._arrastre
        self._arrastre = []
        hablando = bool(seg)
        esperado = 0.0
        # Pausa = el 80% de los últimos `silencio_fin` segundos sin voz (un chasquido suelto
        # de ruido no la reinicia, como pasaba al exigir silencio perfecto).
        ventana: deque[bool] = deque(maxlen=max(1, int(silencio_fin / DUR_BLOQUE)))

        while not self._parar.is_set():
            r = self.mic.leer(timeout=0.5)
            if r is None:
                if espera_max is not None and not hablando:
                    esperado += 0.5
                    if esperado >= espera_max:
                        return None
                continue
            t, b = r
            if self.hablante.ocupado_en(t):  # no escucharse a sí misma
                previo.clear()
                seg, hablando = [], False
                ventana.clear()
                self.vad.reiniciar()
                continue

            p = self.vad.prob(b)
            if not hablando:
                previo.append(b)
                if p >= UMBRAL_HABLA:
                    hablando, seg = True, list(previo)
                    ventana.clear()
                elif espera_max is not None:
                    esperado += DUR_BLOQUE
                    if esperado >= espera_max:
                        return None
                continue

            seg.append(b)
            ventana.append(p < UMBRAL_SILENCIO)
            if len(ventana) == ventana.maxlen and sum(ventana) >= 0.8 * ventana.maxlen:
                return np.concatenate(seg), False
            if len(seg) * DUR_BLOQUE >= max_seg:
                # Dejamos 2 s de solapamiento para no partir la frase al medio.
                self._arrastre = seg[-int(2.0 / DUR_BLOQUE):]
                return np.concatenate(seg), True
        return None

    # ---------- bucle principal ----------
    def bucle(self) -> None:
        self.mic.vaciar()
        log.info('Escuchando. Decí "%s".', "Hola asistente")
        while not self._parar.is_set():
            r = self._segmento(max_seg=8.0, silencio_fin=0.6)
            if r is None:
                continue
            audio, cortado = r
            if len(audio) < self.duracion_minima * SR:
                continue
            self.estadisticas["segmentos"] += 1

            if self.detector.buscar(audio) is None:
                continue
            self.estadisticas["candidatas"] += 1

            try:
                texto = self._transcribir(audio)
            except Exception as e:  # noqa: BLE001
                log.warning("No pude confirmar la frase (¿sin internet?): %s", e)
                continue
            d = self.verificador.buscar(texto)
            if not d.encontrada:
                log.info("Descartada (no era la frase): «%s»", texto)
                continue

            self.estadisticas["activaciones"] += 1
            log.info("¡Activada! «%s»", texto)
            if self.solo_prueba:
                self.hablante.sonido("activado")
                self._arrastre = []
                continue
            self._activado("" if cortado else d.resto)
            self._arrastre = []
            self.vad.reiniciar()
            self.mic.vaciar()

    def _transcribir(self, audio: np.ndarray) -> str:
        self.estadisticas["enviados_openai"] += 1
        pico = float(np.max(np.abs(audio))) if len(audio) else 0.0
        log.info("Enviando %.1f s de audio a OpenAI (volumen máximo %.2f)", len(audio) / SR, pico)
        if pico < 0.05:
            log.warning("El micrófono llega muy bajo. Subí el volumen de entrada en "
                        "Preferencias del Sistema > Sonido > Entrada.")
        try:  # para diagnosticar: siempre queda el último pedido grabado
            (carpeta_base() / "ultimo_pedido.wav").write_bytes(a_wav(audio))
        except OSError:
            pass
        return self.transcriptor.transcribir(audio, prompt=PROMPT_COMANDO).strip()

    def _activado(self, resto: str) -> None:
        try:
            self.al_activar()
        except Exception:  # noqa: BLE001
            log.exception("Error al activar")
        try:
            pedido = resto if len(resto.split()) >= 2 else ""  # "hola asistente, poné ..."
            if not pedido:
                # ¿Siguió hablando de corrido? Lo que dijo mientras se procesaba la frase
                # sigue en la cola del micrófono: no se descarta.
                r = self._segmento(max_seg=15.0, silencio_fin=1.0, espera_max=SIGUE_HABLANDO)
                if r is None:
                    self.hablante.sonido("activado")
                    self.vad.reiniciar()
                    r = self._segmento(max_seg=15.0, silencio_fin=1.0, espera_max=6.0)
                if r is None:
                    self.hablante.sonido("cancelado")
                    return
                pedido = (resto + " " + self._transcribir(r[0])).strip()
                self._arrastre = []
            pedido = pedido.strip()
            if not pedido:
                self.hablante.sonido("cancelado")
                return
            print(f"🎤 {pedido}", flush=True)
            respuesta = self.al_pedido(pedido)
            self.hablante.decir(respuesta)
        except Exception:  # noqa: BLE001
            log.exception("Error procesando el pedido")
            self.hablante.decir("Uy, algo falló. Probá de nuevo.")
        finally:
            try:
                self.al_terminar()
            except Exception:  # noqa: BLE001
                log.exception("Error al terminar")


def crear_escucha(config, al_pedido, al_activar, al_terminar, hablante: Hablante,
                  solo_prueba: bool = False, microfono: int | str | None = None) -> EscuchaVoz:
    mic = Microfono(microfono if microfono is not None else config.microfono)
    escucha = EscuchaVoz(
        microfono=mic,
        vad=VAD(config.vad_agresividad),
        transcriptor=Transcriptor(config.api_key, config.stt_modelo),
        detector=DetectorLocal(config.modelo_vosk, config.frase_local,
                               config.umbral_activacion / 100),
        verificador=DetectorFrase(config.frase_local, config.umbral_activacion),
        hablante=hablante,
        al_pedido=al_pedido,
        al_activar=al_activar,
        al_terminar=al_terminar,
        solo_prueba=solo_prueba,
        duracion_minima=config.duracion_minima_voz,
    )
    mic.iniciar()
    return escucha


__all__ = ["EscuchaVoz", "crear_escucha", "BLOQUE"]
