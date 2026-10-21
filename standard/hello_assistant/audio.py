"""Micrófono, detector de voz (VAD) y sonidos cortos. Todo local."""
from __future__ import annotations

import queue
import threading

import numpy as np

SR = 16000          # Whisper y Silero VAD trabajan a 16 kHz
BLOQUE = 512        # 32 ms por bloque (lo que pide Silero VAD)
DUR_BLOQUE = BLOQUE / SR


class Microfono:
    """Captura continua del micrófono en bloques de 512 muestras float32."""

    def __init__(self, dispositivo: str | int | None = None) -> None:
        self._cola: queue.Queue[np.ndarray] = queue.Queue(maxsize=int(30 / DUR_BLOQUE))
        self._dispositivo = dispositivo
        self._stream = None

    def _callback(self, indata, frames, tiempo, estado) -> None:  # noqa: ARG002
        try:
            self._cola.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def iniciar(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=SR, channels=1, dtype="float32", blocksize=BLOQUE,
            device=self._dispositivo, callback=self._callback,
        )
        self._stream.start()

    def leer(self, timeout: float = 0.5) -> np.ndarray | None:
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
    """Silero VAD en modo streaming (el modelo viene incluido en faster-whisper)."""

    CONTEXTO = 64

    def __init__(self) -> None:
        from faster_whisper.vad import get_vad_model

        self._sesion = get_vad_model().session
        self.reiniciar()

    def reiniciar(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._ctx = np.zeros(self.CONTEXTO, dtype=np.float32)

    def prob(self, bloque: np.ndarray) -> float:
        x = np.concatenate([self._ctx, bloque.astype(np.float32)])[None, :]
        salida, self._h, self._c = self._sesion.run(
            None, {"input": x, "h": self._h, "c": self._c}
        )
        self._ctx = bloque[-self.CONTEXTO:].astype(np.float32)
        return float(np.asarray(salida).reshape(-1)[0])


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
