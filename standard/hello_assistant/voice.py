"""Bucle de voz: escucha continua -> frase de activación (2 pasos) -> pedido -> respuesta.

Paso 1: cada vez que alguien habla, Whisper chico ('base') transcribe y se busca la frase.
Paso 2: si aparece, Whisper grande ('small') vuelve a transcribir EL MISMO audio y la
frase tiene que aparecer otra vez. Recién ahí se activa.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable

import numpy as np

from .audio import BLOQUE, DUR_BLOQUE, SR, VAD, Microfono
from .speaker import Hablante
from .stt import PROMPT_COMANDO, DetectorFrase, Transcriptor

log = logging.getLogger(__name__)

UMBRAL_HABLA = 0.5      # probabilidad de voz para empezar un segmento
UMBRAL_SILENCIO = 0.35  # por debajo de esto cuenta como silencio
PRE_ROLL = 0.4          # segundos de audio previos que se agregan al segmento


class EscuchaVoz:
    def __init__(
        self,
        microfono: Microfono,
        vad: VAD,
        rapido: Transcriptor,
        preciso: Transcriptor,
        detector: DetectorFrase,
        hablante: Hablante,
        al_pedido: Callable[[str], str],
        al_activar: Callable[[], None] = lambda: None,
        al_terminar: Callable[[], None] = lambda: None,
        solo_prueba: bool = False,
    ) -> None:
        self.mic = microfono
        self.vad = vad
        self.rapido = rapido
        self.preciso = preciso
        self.detector = detector
        self.hablante = hablante
        self.al_pedido = al_pedido
        self.al_activar = al_activar
        self.al_terminar = al_terminar
        self.solo_prueba = solo_prueba
        self._parar = threading.Event()
        self._arrastre: list[np.ndarray] = []
        self.estadisticas = {"segmentos": 0, "paso1": 0, "activaciones": 0}

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
        silencio = esperado = 0.0

        while not self._parar.is_set():
            b = self.mic.leer(timeout=0.5)
            if b is None:
                if espera_max is not None and not hablando:
                    esperado += 0.5
                    if esperado >= espera_max:
                        return None
                continue
            if self.hablante.ocupado:  # no escucharse a sí misma
                previo.clear()
                seg, hablando, silencio = [], False, 0.0
                self.vad.reiniciar()
                continue

            p = self.vad.prob(b)
            if not hablando:
                previo.append(b)
                if p >= UMBRAL_HABLA:
                    hablando, seg, silencio = True, list(previo), 0.0
                elif espera_max is not None:
                    esperado += DUR_BLOQUE
                    if esperado >= espera_max:
                        return None
                continue

            seg.append(b)
            silencio = silencio + DUR_BLOQUE if p < UMBRAL_SILENCIO else 0.0
            if silencio >= silencio_fin:
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
            if len(audio) < 0.5 * SR:
                continue
            self.estadisticas["segmentos"] += 1

            t1 = self.rapido.transcribir(audio)
            d1 = self.detector.buscar(t1)
            log.debug("paso 1 (%.0f): %s", d1.puntaje, t1)
            if not d1.encontrada:
                continue
            self.estadisticas["paso1"] += 1

            t2 = self.preciso.transcribir(audio)
            d2 = self.detector.buscar(t2)
            if not d2.encontrada:
                log.info("Descartada en el paso 2 (%.0f): «%s»", d2.puntaje, t2)
                continue

            self.estadisticas["activaciones"] += 1
            log.info("¡Activada! (%.0f/%.0f) «%s»", d1.puntaje, d2.puntaje, t2)
            if self.solo_prueba:
                self.hablante.sonido("activado")
                self._arrastre = []
                continue
            self._activado("" if cortado else d2.resto)
            self._arrastre = []
            self.vad.reiniciar()
            self.mic.vaciar()

    def _activado(self, resto: str) -> None:
        try:
            self.al_activar()
        except Exception:  # noqa: BLE001
            log.exception("Error al activar")
        try:
            if len(resto.split()) >= 2:
                pedido = resto  # "hola asistente poné ..." todo de corrido
            else:
                self.hablante.sonido("activado")
                self.vad.reiniciar()
                self.mic.vaciar()
                r = self._segmento(max_seg=15.0, silencio_fin=1.0, espera_max=6.0)
                if r is None:
                    self.hablante.sonido("cancelado")
                    return
                pedido = self.preciso.transcribir(r[0], prompt=PROMPT_COMANDO)
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
        vad=VAD(),
        rapido=Transcriptor(config.whisper_activacion, beam=1),
        preciso=Transcriptor(config.whisper_modelo, beam=5),
        detector=DetectorFrase(config.frase_activacion, config.umbral_activacion),
        hablante=hablante,
        al_pedido=al_pedido,
        al_activar=al_activar,
        al_terminar=al_terminar,
        solo_prueba=solo_prueba,
    )
    mic.iniciar()
    return escucha


__all__ = ["EscuchaVoz", "crear_escucha", "BLOQUE"]
