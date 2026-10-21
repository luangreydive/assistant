"""Voz a texto local con faster-whisper + detección de la frase de activación."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz

from .config import carpeta_base
from .music_index import normalizar

log = logging.getLogger(__name__)

PROMPT_COMANDO = (
    "Pedido a un asistente de voz en español rioplatense. Por ejemplo: poné el disco, "
    "pausá, siguiente, poné un temporizador de diez minutos, ¿cuánto falta?"
)


class Transcriptor:
    def __init__(self, modelo: str, beam: int = 1) -> None:
        from faster_whisper import WhisperModel

        destino = carpeta_base() / "models" / "whisper"
        destino.mkdir(parents=True, exist_ok=True)
        log.info("Cargando Whisper '%s' (la primera vez se descarga)...", modelo)
        self._modelo = WhisperModel(modelo, device="cpu", compute_type="int8",
                                    download_root=str(destino))
        self._beam = beam

    def transcribir(self, audio: np.ndarray, prompt: str | None = None) -> str:
        segmentos, _ = self._modelo.transcribe(
            audio, language="es", beam_size=self._beam, temperature=0.0,
            condition_on_previous_text=False, without_timestamps=True,
            vad_filter=False, initial_prompt=prompt,
        )
        return " ".join(s.text.strip() for s in segmentos).strip()


@dataclass
class Deteccion:
    encontrada: bool
    puntaje: float
    resto: str  # lo que se dijo después de la frase


class DetectorFrase:
    """Busca la frase (p. ej. 'hola asistente') en un texto, tolerando cómo Whisper la escriba:
    'Hola, asistente', 'ola asistente', 'hola asistente.', etc.
    'asistente' solo (sin 'hola') NO alcanza el umbral por defecto."""

    def __init__(self, frase: str, umbral: float = 85) -> None:
        self.objetivo = normalizar(frase).replace(" ", "")
        self.primera = normalizar(frase).split()[0]
        self.umbral = umbral

    def buscar(self, texto: str) -> Deteccion:
        palabras = normalizar(texto).split()
        mejor, fin_mejor = 0.0, 0
        for i in range(len(palabras)):
            for n in range(1, 5):
                if i + n > len(palabras):
                    break
                p = fuzz.ratio("".join(palabras[i:i + n]), self.objetivo)
                # "la asistente" se parece mucho a "hola asistente": la primera palabra
                # también tiene que parecerse ("ola" sí, "la" no).
                if n > 1 and fuzz.ratio(palabras[i], self.primera) < 75:
                    continue
                if p > mejor:
                    mejor, fin_mejor = p, i + n
        if mejor >= self.umbral:
            return Deteccion(True, mejor, " ".join(palabras[fin_mejor:]))
        return Deteccion(False, mejor, "")
