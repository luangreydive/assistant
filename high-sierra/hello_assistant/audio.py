"""Micrófono, detector de voz (VAD) y sonidos cortos. Todo local."""
from __future__ import annotations

import queue
import threading
import time

import numpy as np

SR = 16000          # el VAD y la transcripción trabajan a 16 kHz
BLOQUE = 480        # 30 ms por bloque (webrtcvad acepta 10, 20 o 30 ms)
DUR_BLOQUE = BLOQUE / SR


class Microfono:
    """Captura continua del micrófono en bloques de 480 muestras float32.

    Cada bloque se guarda con la hora en que se grabó, para poder descartar justo lo que
    se grabó mientras la app hablaba (y no lo que dijiste mientras procesaba)."""

    def __init__(self, dispositivo: str | int | None = None) -> None:
        self._cola: queue.Queue[tuple[float, np.ndarray]] = queue.Queue(maxsize=int(30 / DUR_BLOQUE))
        self._dispositivo = dispositivo
        self._stream = None

    def _callback(self, indata, frames, tiempo, estado) -> None:  # noqa: ARG002
        try:
            self._cola.put_nowait((time.monotonic(), indata[:, 0].copy()))
        except queue.Full:
            pass

    def iniciar(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=SR, channels=1, dtype="float32", blocksize=BLOQUE,
            device=self._dispositivo, callback=self._callback,
        )
        self._stream.start()

    def leer(self, timeout: float = 0.5) -> tuple[float, np.ndarray] | None:
        try:
            return self._cola.get(timeout=timeout)
        except queue.Empty:
            return None

    def vaciar(self) -> None:
        while True:
            try:
                self._cola.get_nowait()
            except queue.Empty:
                return

    def detener(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class VAD:
    """WebRTC VAD (liviano, sin onnxruntime, funciona en macOS 10.13).

    Devuelve 1.0 o 0.0 para mantener la misma interfaz que el VAD anterior."""

    def __init__(self, agresividad: int = 2) -> None:
        import webrtcvad

        self._vad = webrtcvad.Vad(max(0, min(3, agresividad)))

    def reiniciar(self) -> None:
        pass  # webrtcvad no guarda estado entre bloques

    def prob(self, bloque: np.ndarray) -> float:
        pcm = (np.clip(bloque, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        return 1.0 if self._vad.is_speech(pcm, SR) else 0.0


# ---------- sonidos ----------
_lock_sonido = threading.Lock()


def _tono(frecs: list[float], dur: float = 0.09, vol: float = 0.25, sr: int = 44100) -> np.ndarray:
    partes = []
    for f in frecs:
        t = np.arange(int(sr * dur)) / sr
        onda = np.sin(2 * np.pi * f * t)
        env = np.minimum(1, np.minimum(t, t[::-1]) / 0.01)  # sin clics
        partes.append(onda * env * vol)
    return np.concatenate(partes).astype(np.float32)


SONIDOS = {
    "activado": _tono([660, 990]),
    "cancelado": _tono([660, 440]),
    "alarma": np.concatenate([_tono([880, 0, 880, 0, 880], dur=0.15, vol=0.4)] * 3),
}


def reproducir_sonido(nombre: str) -> None:
    import sounddevice as sd

    with _lock_sonido:
        sd.play(SONIDOS[nombre], 44100)
        sd.wait()
