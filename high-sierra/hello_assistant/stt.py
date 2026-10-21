"""Detección de la frase de activación (Vosk local + confirmación) y voz a texto con OpenAI."""
from __future__ import annotations

import io
import json
import logging
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from openai import OpenAI
from rapidfuzz import fuzz

from .audio import SR
from .music_index import normalizar

log = logging.getLogger(__name__)

# Ojo: el modelo a veces "devuelve" el prompt cuando no entiende el audio: se filtra.
PROMPT_COMANDO = (
    "Pedido a un asistente de voz en español rioplatense. Por ejemplo: poné el disco, "
    "pausá, siguiente, poné un temporizador de diez minutos, ¿cuánto falta?"
)


GANANCIA_MAX = 10.0  # micrófonos bajos (p. ej. Macs viejas): se sube hasta 10 veces


def normalizar_volumen(audio: np.ndarray) -> np.ndarray:
    pico = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if pico <= 1e-4:
        return audio
    return audio * min(GANANCIA_MAX, 0.9 / pico)


def quitar_eco_del_prompt(texto: str, prompt: str | None) -> str:
    """Saca las frases del prompt que el modelo haya repetido como si fueran lo dicho."""
    if not prompt or not texto:
        return texto
    limpio = normalizar(texto)
    original = limpio
    for frase in prompt.replace("?", ".").replace("¿", "").replace(":", ".").split("."):
        frase = normalizar(frase)
        if len(frase.split()) >= 3 and frase in limpio:
            limpio = limpio.replace(frase, " ")
    if fuzz.ratio(normalizar(texto), normalizar(prompt)) >= 80:
        limpio = ""
    limpio = " ".join(limpio.split())
    if limpio != original:
        log.debug("Descarto eco del prompt: «%s» -> «%s»", texto, limpio)
        return limpio
    return texto


def a_wav(audio: np.ndarray) -> bytes:
    """float32 mono a 16 kHz -> WAV PCM 16 bits en memoria."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    return buf.getvalue()


class Transcriptor:
    def __init__(self, api_key: str, modelo: str) -> None:
        self._cliente = OpenAI(api_key=api_key, timeout=30, max_retries=1)
        self._modelo = modelo

    def transcribir(self, audio: np.ndarray, prompt: str | None = None) -> str:
        r = self._cliente.audio.transcriptions.create(
            model=self._modelo,
            file=("audio.wav", a_wav(normalizar_volumen(audio)), "audio/wav"),
            language="es",
            prompt=prompt or "",
        )
        texto = (r.text or "").strip()
        log.debug("Pico del audio %.3f -> «%s»", float(np.max(np.abs(audio))) if len(audio) else 0, texto)
        return quitar_eco_del_prompt(texto, prompt)


class DetectorLocal:
    """Busca la frase de activación en el propio equipo con Vosk (sin internet, sin costo).

    Vosk trabaja con una gramática cerrada: solo puede reconocer las palabras de la frase
    o "[unk]" (desconocido). Hay activación si aparecen todas las palabras seguidas, pegadas
    (como cuando se dicen de corrido) y con confianza suficiente.

    Vosk no informa los "[unk]", así que "hola... (charla)... súper... puré" puede salir como
    "hola asistente": por eso se exige que entre palabra y palabra haya poco tiempo."""

    PAUSA_MAX = 0.6  # segundos entre palabras de la frase (dicha de corrido es <0,45)

    def __init__(self, ruta_modelo: Path, frase: str = "hola asistente",
                 confianza: float = 0.85) -> None:
        import vosk

        if not Path(ruta_modelo).is_dir():
            raise RuntimeError(f"No encuentro el modelo de Vosk en {ruta_modelo}. "
                               "Corré ./iniciar.sh para descargarlo.")
        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self._modelo = vosk.Model(str(ruta_modelo))
        self.palabras = normalizar(frase).split()
        self._gramatica = json.dumps([" ".join(self.palabras), "[unk]"])
        self.confianza = confianza

    def buscar(self, audio: np.ndarray) -> float | None:
        """Devuelve el segundo en que termina la frase dentro del audio, o None."""
        rec = self._vosk.KaldiRecognizer(self._modelo, SR, self._gramatica)
        rec.SetWords(True)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        for i in range(0, len(pcm), 8000):
            rec.AcceptWaveform(pcm[i:i + 8000])
        resultado = json.loads(rec.FinalResult()).get("result", [])
        n = len(self.palabras)
        for i in range(len(resultado) - n + 1):
            tramo = resultado[i:i + n]
            if (
                [w["word"] for w in tramo] == self.palabras
                and all(w["conf"] >= self.confianza for w in tramo)
                and all(b["start"] - a["end"] <= self.PAUSA_MAX for a, b in zip(tramo, tramo[1:]))
            ):
                log.debug("Frase detectada (confianzas %s)", [round(w["conf"], 2) for w in tramo])
                return float(tramo[-1]["end"])
        log.debug("Vosk: %s", " ".join(w["word"] for w in resultado) or "-")
        return None


@dataclass
class Deteccion:
    encontrada: bool
    puntaje: float
    resto: str  # lo que se dijo después de la frase


class DetectorFrase:
    """Busca la frase (p. ej. 'hola asistente') en un texto, tolerando cómo se transcriba:
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
