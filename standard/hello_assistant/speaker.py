"""Texto a voz local con Piper."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from .audio import reproducir_sonido
from .config import carpeta_base

log = logging.getLogger(__name__)

VOCES_RESPALDO = ["es_AR-daniela-high", "es_MX-claude-high", "es_ES-davefx-medium"]


def asegurar_voz(nombre: str) -> Path:
    """Devuelve la ruta del modelo de voz; lo descarga una sola vez si falta."""
    from piper.download_voices import download_voice

    carpeta = carpeta_base() / "models" / "piper"
    carpeta.mkdir(parents=True, exist_ok=True)
    for voz in [nombre] + [v for v in VOCES_RESPALDO if v != nombre]:
        ruta = carpeta / f"{voz}.onnx"
        if ruta.exists() and ruta.stat().st_size > 0:
            return ruta
        try:
            log.info("Descargando la voz %s (solo la primera vez)...", voz)
            download_voice(voz, carpeta)
            return ruta
        except Exception as e:  # noqa: BLE001
            log.warning("No pude descargar la voz %s: %s", voz, e)
            for f in (ruta, carpeta / f"{voz}.onnx.json"):
                f.unlink(missing_ok=True)
    raise RuntimeError("No pude conseguir ninguna voz de Piper.")


class Hablante:
    def __init__(self, voz: str, velocidad: float = 1.0) -> None:
        from piper import PiperVoice, SynthesisConfig

        self._voz = PiperVoice.load(str(asegurar_voz(voz)))
        self._cfg = SynthesisConfig(length_scale=1.0 / max(0.5, velocidad))
        self._lock = threading.Lock()
        self._hablando = threading.Event()
        self._fin = 0.0

    @property
    def ocupado(self) -> bool:
        """True mientras suena la voz o un sonido (y un instante después, por el eco)."""
        return self._hablando.is_set() or time.monotonic() - self._fin < 0.4

    def decir(self, texto: str) -> None:
        import sounddevice as sd

        texto = texto.strip()
        if not texto:
            return
        print(f"🗣  {texto}", flush=True)
        with self._lock:
            self._hablando.set()
            try:
                salida = None
                for trozo in self._voz.synthesize(texto, syn_config=self._cfg):
                    if salida is None:
                        salida = sd.OutputStream(samplerate=trozo.sample_rate, channels=1,
                                                 dtype="int16")
                        salida.start()
                    salida.write(np.ascontiguousarray(trozo.audio_int16_array.reshape(-1, 1)))
                if salida is not None:
                    time.sleep(0.15)
                    salida.stop()
                    salida.close()
            except Exception:  # noqa: BLE001
                log.exception("Error reproduciendo la voz")
            finally:
                self._fin = time.monotonic()
                self._hablando.clear()

    def sonido(self, nombre: str) -> None:
        with self._lock:
            self._hablando.set()
            try:
                reproducir_sonido(nombre)
            except Exception:  # noqa: BLE001
                log.exception("Error reproduciendo sonido")
            finally:
                self._fin = time.monotonic()
                self._hablando.clear()
