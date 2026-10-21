"""Texto a voz con la API de OpenAI (se reproduce mientras llega)."""
from __future__ import annotations

import logging
import threading
import time

import numpy as np
from openai import OpenAI

from .audio import reproducir_sonido

log = logging.getLogger(__name__)

SR_TTS = 24000  # el formato "pcm" de OpenAI es int16 mono a 24 kHz


class Hablante:
    def __init__(self, api_key: str, modelo: str, voz: str, instrucciones: str,
                 velocidad: float = 1.0) -> None:
        self._cliente = OpenAI(api_key=api_key, timeout=60, max_retries=1)
        self._modelo = modelo
        self._voz = voz
        self._instrucciones = instrucciones
        self._velocidad = max(0.25, min(4.0, velocidad))
        self._lock = threading.Lock()
        self._hablando = threading.Event()
        self._inicio = 0.0
        self._fin = 0.0

    @property
    def ocupado(self) -> bool:
        """True mientras suena la voz o un sonido (y un instante después, por el eco)."""
        return self._hablando.is_set() or time.monotonic() - self._fin < 0.4

    def ocupado_en(self, t: float) -> bool:
        """True si en el instante t (time.monotonic) sonaba la voz o un sonido (+0,4 s de eco)."""
        if self._hablando.is_set() and t >= self._inicio:
            return True
        return self._inicio <= t <= self._fin + 0.4

    def _empezar(self) -> None:
        self._inicio = time.monotonic()
        self._hablando.set()

    def decir(self, texto: str) -> None:
        import sounddevice as sd

        texto = texto.strip()
        if not texto:
            return
        print(f"🗣  {texto}", flush=True)
        with self._lock:
            self._empezar()
            try:
                extra = {"instructions": self._instrucciones} if self._instrucciones else {}
                with self._cliente.audio.speech.with_streaming_response.create(
                    model=self._modelo, voice=self._voz, input=texto,
                    response_format="pcm", speed=self._velocidad, **extra,
                ) as resp, sd.OutputStream(samplerate=SR_TTS, channels=1, dtype="int16") as salida:
                    resto = b""
                    for trozo in resp.iter_bytes(4800):
                        datos = resto + trozo
                        corte = len(datos) - len(datos) % 2  # muestras de 2 bytes enteras
                        resto = datos[corte:]
                        if corte:
                            muestras = np.frombuffer(datos[:corte], dtype="<i2").reshape(-1, 1)
                            salida.write(np.ascontiguousarray(muestras))
                    time.sleep(0.15)
            except Exception:  # noqa: BLE001
                log.exception("Error reproduciendo la voz")
            finally:
                self._fin = time.monotonic()
                self._hablando.clear()

    def sonido(self, nombre: str) -> None:
        with self._lock:
            self._empezar()
            try:
                reproducir_sonido(nombre)
            except Exception:  # noqa: BLE001
                log.exception("Error reproduciendo sonido")
            finally:
                self._fin = time.monotonic()
                self._hablando.clear()
