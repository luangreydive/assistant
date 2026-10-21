"""Herramientas que el LLM puede pedir que la app ejecute (todas locales)."""
from __future__ import annotations

import logging
from typing import Any

from .music_index import IndiceMusica
from .player import ErrorReproductor, Reproductor
from .timers import Temporizadores, formatear_duracion

log = logging.getLogger(__name__)


def _fn(nombre: str, descripcion: str, propiedades: dict, requeridos: list[str]) -> dict:
    return {
        "type": "function",
        "name": nombre,
        "description": descripcion,
        "parameters": {
            "type": "object",
            "properties": propiedades,
            "required": requeridos,
            "additionalProperties": False,
        },
    }


ESQUEMAS: list[dict] = [
    _fn(
        "buscar_en_biblioteca",
        "Busca en la biblioteca local de música y videos (series, películas, recitales, etc.) "
        "por nombre de carpeta (disco o colección) o de archivo (canción, episodio, película, "
        "video). Tolera errores de escritura. Devuelve candidatos con su id, si es video, y un "
        "puntaje de coincidencia de 0 a 100. tipo='disco' busca carpetas, tipo='cancion' busca "
        "archivos sueltos (de audio o de video).",
        {
            "consulta": {"type": "string", "description": "Texto a buscar, p. ej. 'bohemian rhapsody'."},
            "tipo": {"type": "string", "enum": ["cancion", "disco", "cualquiera"]},
        },
        ["consulta", "tipo"],
    ),
    _fn(
        "reproducir",
        "Reproduce un archivo (canción, episodio, película o video) o una carpeta completa "
        "(disco o colección) usando el id devuelto por buscar_en_biblioteca. "
        "Reemplaza lo que esté sonando.",
        {
            "tipo": {"type": "string", "enum": ["cancion", "disco"]},
            "id": {"type": "integer"},
        },
        ["tipo", "id"],
    ),
    _fn(
        "reproducir_aleatorio",
        "Reproduce música al azar: un disco entero o una mezcla de canciones de toda la biblioteca.",
        {"tipo": {"type": "string", "enum": ["disco", "canciones"]}},
        ["tipo"],
    ),
    _fn(
        "controlar_reproduccion",
        "Controla lo que está sonando.",
        {
            "accion": {
                "type": "string",
                "enum": ["pausar", "reanudar", "siguiente", "anterior", "detener",
                         "subir_volumen", "bajar_volumen", "estado"],
            }
        },
        ["accion"],
    ),
    _fn(
        "iniciar_temporizador",
        "Inicia un temporizador. Convertí la duración pedida a segundos.",
        {
            "segundos": {"type": "integer", "minimum": 1},
            "etiqueta": {"type": "string", "description": "Nombre corto, p. ej. 'pasta'. Vacío si no se dijo."},
        },
        ["segundos", "etiqueta"],
    ),
    _fn(
        "consultar_temporizadores",
        "Lista los temporizadores activos y cuánto le falta a cada uno.",
        {},
        [],
    ),
    _fn(
        "cancelar_temporizador",
        "Cancela temporizadores. Usá la etiqueta si el usuario la nombró, o todos=true.",
        {
            "etiqueta": {"type": "string", "description": "Etiqueta a cancelar, vacío si no aplica."},
            "todos": {"type": "boolean"},
        },
        ["etiqueta", "todos"],
    ),
]


class Herramientas:
    def __init__(self, indice: IndiceMusica, reproductor: Reproductor,
                 temporizadores: Temporizadores) -> None:
        self.indice = indice
        self.reproductor = reproductor
        self.temporizadores = temporizadores

    def ejecutar(self, nombre: str, args: dict[str, Any]) -> dict:
        metodo = getattr(self, f"_h_{nombre}", None)
        if metodo is None:
            return {"error": f"Herramienta desconocida: {nombre}"}
        try:
            return metodo(**args)
        except ErrorReproductor as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001
            log.exception("Error en herramienta %s", nombre)
            return {"error": f"Falló {nombre}: {e}"}

    # ---------- biblioteca (música y videos) ----------
    def _h_buscar_en_biblioteca(self, consulta: str, tipo: str = "cualquiera") -> dict:
        if not self.indice.listo.wait(timeout=30):
            return {"error": "Todavía estoy indexando la biblioteca, probá en unos segundos."}
        res: dict[str, Any] = {"biblioteca": self.indice.totales}
        if tipo in ("disco", "cualquiera"):
            res["discos"] = self.indice.buscar_discos(consulta)
        if tipo in ("cancion", "cualquiera"):
            res["canciones"] = self.indice.buscar_canciones(consulta)
        return res

    def _h_reproducir(self, tipo: str, id: int) -> dict:  # noqa: A002
        if tipo == "disco":
            disco = self.indice.disco(id)
            if not disco:
                return {"error": "No existe ese disco."}
            pistas = self.indice.pistas_de_disco(id)
            self.reproductor.reproducir([p.ruta for p in pistas])
            return {"ok": True, "disco": disco.nombre, "pistas": len(pistas),
                    "primera": pistas[0].titulo if pistas else None}
        pista = self.indice.pista(id)
        if not pista:
            return {"error": "No existe esa canción."}
        self.reproductor.reproducir([pista.ruta])
        disco = self.indice.disco(pista.disco_id)
        return {"ok": True, "cancion": pista.titulo, "disco": disco.nombre if disco else None}

    def _h_reproducir_aleatorio(self, tipo: str) -> dict:
        pistas = self.indice.aleatorio(tipo)
        if not pistas:
            return {"error": "La biblioteca está vacía."}
        self.reproductor.reproducir([p.ruta for p in pistas])
        disco = self.indice.disco(pistas[0].disco_id)
        return {"ok": True, "tipo": tipo, "pistas": len(pistas),
                "disco": disco.nombre if (disco and tipo == "disco") else None}

    def _h_controlar_reproduccion(self, accion: str) -> dict:
        r = self.reproductor
        if accion == "estado":
            return r.estado()
        if not r.estado().get("reproduciendo"):
            return {"error": "No está sonando nada."}
        acciones = {
            "pausar": r.pausar, "reanudar": r.reanudar, "siguiente": r.siguiente,
            "anterior": r.anterior, "detener": r.detener,
        }
        if accion in acciones:
            acciones[accion]()
            return {"ok": True}
        if accion in ("subir_volumen", "bajar_volumen"):
            vol = r.cambiar_volumen(10 if accion == "subir_volumen" else -10)
            return {"ok": True, "volumen": round(vol or 0)}
        return {"error": f"Acción desconocida: {accion}"}

    # ---------- temporizadores ----------
    def _h_iniciar_temporizador(self, segundos: int, etiqueta: str = "") -> dict:
        t = self.temporizadores.iniciar(segundos, etiqueta)
        return {"ok": True, "id": t.id, "duracion": formatear_duracion(segundos),
                "etiqueta": t.etiqueta or None}

    def _h_consultar_temporizadores(self) -> dict:
        return {"activos": self.temporizadores.listar()}

    def _h_cancelar_temporizador(self, etiqueta: str = "", todos: bool = False) -> dict:
        n = self.temporizadores.cancelar(etiqueta=etiqueta or None, todos=todos)
        return {"cancelados": n, "quedan": len(self.temporizadores.listar())}
