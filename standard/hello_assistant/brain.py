"""Conexión con OpenAI (Responses API) + bucle de herramientas.

Es el ÚNICO punto de la app que sale a internet. La búsqueda web la hace el
mismo modelo con la herramienta integrada `web_search` de OpenAI.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI, OpenAIError

from .config import Config
from .tools import ESQUEMAS, Herramientas

log = logging.getLogger(__name__)

MAX_RONDAS = 6
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

INSTRUCCIONES = """Sos Hello Assistant, un asistente de voz que corre en una computadora de casa.
Hablás en español rioplatense, con calidez y en pocas palabras.

Tus respuestas se leen en voz alta, así que:
- Respondé en 1 a 3 oraciones, salvo que te pidan más detalle.
- Nada de markdown, listas, emojis, links ni URLs. Escribí los números como se dicen si ayuda.
- No nombres las fuentes salvo que te lo pidan.

Preguntas: si no estás seguro de la respuesta, o depende de algo actual (noticias, clima,
precios, resultados, horarios, quién ocupa un cargo), usá la búsqueda web antes de responder.

Biblioteca: es local y tiene música Y videos (series, películas, recitales, videoclips, etc.).
Solo conocés los nombres de las carpetas (discos o colecciones) y de los archivos (canciones,
episodios, películas). Cualquier cosa que te pidan reproducir puede estar ahí.
- Ante CUALQUIER pedido de reproducir algo (canción, disco, serie, episodio, película, video),
  buscá siempre con buscar_en_biblioteca antes de responder. Nunca digas que no podés
  reproducir algo, ni que no está, sin haberlo buscado antes. Nunca inventes ids.
- El pedido viene de un reconocimiento de voz: los nombres en inglés pueden llegar mal escritos
  o "a la española". Si no hay buenos resultados (coincidencia menor a 75), probá de nuevo con
  otras grafías probables, con el nombre original, o solo con una parte del nombre.
- Si te piden una colección entera (un disco, una carpeta), reproducila completa. Si te piden
  un archivo puntual (una canción, un episodio, una película), reproducí ese archivo.
- Si hay varios candidatos parecidos, elegí el de mayor coincidencia. Si después de buscar no
  encontrás nada, decí que no está en la biblioteca.
- Al reproducir, confirmá brevemente qué pusiste (p. ej. "Pongo Abbey Road").

Temporizadores: convertí la duración a segundos. Confirmá la duración en palabras.

Fecha y hora actual: {ahora}.{ubicacion}"""


def limpiar_para_voz(texto: str) -> str:
    texto = re.sub(r"\(\s*\[[^\]]*\]\([^)]*\)\s*\)", "", texto)   # ([fuente](url))
    texto = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", texto)          # [texto](url) -> texto
    texto = re.sub(r"https?://\S+", "", texto)
    texto = re.sub(r"[*_`#>]+", "", texto)
    texto = re.sub(r"^\s*[-•]\s+", "", texto, flags=re.M)
    texto = re.sub(r"\s+", " ", texto)
    return re.sub(r"\s+([.,;:!?])", r"\1", texto).strip()


class Cerebro:
    def __init__(self, config: Config, herramientas: Herramientas) -> None:
        self.config = config
        self.herramientas = herramientas
        self.cliente = OpenAI(api_key=config.api_key, timeout=60, max_retries=2)
        busqueda = {"type": "web_search", "search_context_size": "low"}
        ubicacion = {k: v for k, v in (("country", config.pais), ("city", config.ciudad),
                                       ("timezone", config.zona_horaria)) if v}
        if ubicacion:  # opcional: solo si está en el .env
            busqueda["user_location"] = {"type": "approximate", **ubicacion}
        self.tools = [busqueda, *ESQUEMAS]

    def _instrucciones(self) -> str:
        try:
            ahora = datetime.now(ZoneInfo(self.config.zona_horaria))
        except Exception:  # noqa: BLE001  (vacía o inválida: la hora de la compu)
            ahora = datetime.now().astimezone()
        lugar = ", ".join(x for x in (self.config.ciudad, self.config.pais) if x)
        return INSTRUCCIONES.format(
            ahora=f"{DIAS[ahora.weekday()]} {ahora:%d/%m/%Y %H:%M}",
            ubicacion=f" Ubicación aproximada: {lugar}." if lugar else "",
        )

    def _crear(self, **kwargs):
        return self.cliente.responses.create(
            model=self.config.modelo,
            instructions=self._instrucciones(),
            tools=self.tools,
            reasoning={"effort": self.config.esfuerzo},
            **kwargs,
        )

    def preguntar(self, texto: str) -> str:
        """Cada pregunta es independiente (sin memoria entre preguntas)."""
        try:
            resp = self._crear(input=texto)
            for _ in range(MAX_RONDAS):
                llamadas = [o for o in resp.output if o.type == "function_call"]
                if not llamadas:
                    break
                salidas = []
                for ll in llamadas:
                    try:
                        args = json.loads(ll.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    resultado = self.herramientas.ejecutar(ll.name, args)
                    log.info("Herramienta %s(%s) -> %s", ll.name, args, resultado)
                    salidas.append({
                        "type": "function_call_output",
                        "call_id": ll.call_id,
                        "output": json.dumps(resultado, ensure_ascii=False),
                    })
                resp = self._crear(input=salidas, previous_response_id=resp.id)
            return limpiar_para_voz(resp.output_text or "") or "Listo."
        except OpenAIError as e:
            log.error("Error de OpenAI: %s", e)
            return "No pude conectarme con el modelo. Revisá la conexión a internet o la clave de API."
