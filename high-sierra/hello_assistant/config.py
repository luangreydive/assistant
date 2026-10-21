"""Carga la configuración desde el archivo .env."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def carpeta_base() -> Path:
    """Carpeta del proyecto (o del ejecutable cuando la app está empaquetada)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class ErrorConfig(Exception):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str
    modelo: str
    esfuerzo: str
    carpetas_musica: list[Path]
    mpv_ruta: str | None
    mostrar_video: bool
    pais: str
    ciudad: str
    zona_horaria: str
    frase_local: str
    modelo_vosk: Path
    umbral_activacion: float
    stt_modelo: str
    tts_modelo: str
    tts_voz: str
    tts_instrucciones: str
    velocidad_voz: float
    vad_agresividad: int
    duracion_minima_voz: float
    microfono: str | int | None


def _si_no(valor: str | None, defecto: bool) -> bool:
    if valor is None or not valor.strip():
        return defecto
    return valor.strip().lower() in {"si", "sí", "s", "true", "1", "yes"}


def cargar() -> Config:
    load_dotenv(carpeta_base() / ".env")
    load_dotenv(Path.cwd() / ".env")  # no pisa lo ya cargado

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    carpetas = leer_carpetas(os.getenv("MUSICA_CARPETAS", ""), os.getenv("MUSICA_CARPETA", ""))

    faltan = [n for n, v in (("OPENAI_API_KEY", api_key), ("MUSICA_CARPETAS", carpetas)) if not v]
    if faltan:
        raise ErrorConfig(
            f"Faltan valores en el archivo .env: {', '.join(faltan)}. "
            "Copiá .env.example como .env y completalo."
        )

    return Config(
        api_key=api_key,
        modelo=os.getenv("OPENAI_MODELO", "gpt-6-luna").strip(),
        esfuerzo=os.getenv("OPENAI_ESFUERZO", "low").strip(),
        carpetas_musica=carpetas,
        mpv_ruta=(os.getenv("MPV_RUTA") or "").strip() or None,
        mostrar_video=_si_no(os.getenv("MOSTRAR_VIDEO"), True),
        pais=os.getenv("UBICACION_PAIS", "").strip(),
        ciudad=os.getenv("UBICACION_CIUDAD", "").strip(),
        zona_horaria=os.getenv("ZONA_HORARIA", "").strip(),
        frase_local=os.getenv("FRASE_ACTIVACION_LOCAL", "hola asistente").strip(),
        modelo_vosk=Path(os.getenv("MODELO_VOSK", "").strip()
                         or carpeta_base() / "models" / "vosk-model-small-es-0.42").expanduser(),
        umbral_activacion=float(os.getenv("UMBRAL_ACTIVACION", "85")),
        stt_modelo=os.getenv("STT_MODELO", "gpt-4o-mini-transcribe").strip(),
        tts_modelo=os.getenv("TTS_MODELO", "gpt-4o-mini-tts").strip(),
        tts_voz=os.getenv("TTS_VOZ", "coral").strip(),
        tts_instrucciones=os.getenv(
            "TTS_INSTRUCCIONES", "Hablá en español rioplatense, con tono cálido y natural."
        ).strip(),
        velocidad_voz=float(os.getenv("VELOCIDAD_VOZ", "1.0")),
        vad_agresividad=int(os.getenv("VAD_AGRESIVIDAD", "2")),
        duracion_minima_voz=float(os.getenv("DURACION_MINIMA_VOZ", "0.6")),
        microfono=_microfono(os.getenv("MICROFONO")),
    )


def leer_carpetas(varias: str, una: str = "") -> list[Path]:
    """MUSICA_CARPETAS separadas por '|'. También acepta la vieja MUSICA_CARPETA (una sola)."""
    vistas: list[Path] = []
    for texto in (varias or "").split("|") + [una or ""]:
        texto = texto.strip().strip('"').strip("'").strip()
        if not texto:
            continue
        ruta = Path(texto).expanduser()
        if ruta not in vistas:
            vistas.append(ruta)
    return vistas


def _microfono(valor: str | None) -> str | int | None:
    if not valor or not valor.strip():
        return None
    v = valor.strip()
    return int(v) if v.isdigit() else v
