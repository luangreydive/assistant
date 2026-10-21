"""Índice local de la música, armado solo con nombres de carpetas y archivos.

Se pueden indexar varias carpetas raíz (MUSICA_CARPETAS en el .env).
El disco es la carpeta que contiene directamente los archivos, a cualquier
profundidad (p. ej. RAIZ/usuario/Disco/archivo.ext -> "Disco"). Las carpetas
intermedias no se indexan. Archivos sueltos en una raíz van a un disco con el
nombre de esa raíz. Las raíces que no existen se saltean con un aviso.
"""
from __future__ import annotations

import logging
import os
import random
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

EXT_AUDIO = {
    ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".aif", ".aiff",
    ".wma", ".alac", ".ape", ".wv", ".mka", ".mpc", ".dsf", ".dff", ".ac3", ".dts",
}
EXT_VIDEO = {
    ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".mpg", ".mpeg",
    ".ts", ".m2ts", ".3gp", ".vob", ".ogv",
}
EXTENSIONES = EXT_AUDIO | EXT_VIDEO


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = texto.replace("&", " y ")
    texto = re.sub(r"[^a-z0-9ñ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


_NUM_CON_SEPARADOR = re.compile(r"^\s*(?:\d{1,2}\s*[-.]\s*)?\d{1,3}\s*[-._)\]]+\s*")
_NUM_CON_CERO = re.compile(r"^\s*0\d\s+")


def titulo_desde_archivo(nombre_sin_ext: str) -> str:
    """'01 - Canción' -> 'Canción'. Respeta títulos como '99 Luftballons'."""
    t = _NUM_CON_SEPARADOR.sub("", nombre_sin_ext, count=1)
    t = _NUM_CON_CERO.sub("", t, count=1)
    t = t.replace("_", " ").strip()
    return t or nombre_sin_ext


def _orden_natural(texto: str) -> list:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", texto)]


@dataclass
class Pista:
    id: int
    disco_id: int
    titulo: str
    ruta: Path
    es_video: bool
    norm: str


@dataclass
class Disco:
    id: int
    nombre: str
    ruta: Path
    norm: str
    pistas: list[int] = field(default_factory=list)


class IndiceMusica:
    def __init__(self, raices: list[Path]) -> None:
        self.raices = raices
        self._lock = threading.Lock()
        self._discos: list[Disco] = []
        self._pistas: list[Pista] = []
        self._norm_discos: dict[int, str] = {}
        self._norm_pistas: dict[int, str] = {}
        self._norm_pistas_con_disco: dict[int, str] = {}
        self.listo = threading.Event()
        self._observador = None
        self._rescan_timer: threading.Timer | None = None

    # ---------- escaneo ----------
    def escanear(self) -> None:
        """Cada carpeta que contiene archivos reproducibles es un disco.
        Las carpetas de más arriba (p. ej. una carpeta por usuario o por fuente de descarga) no se indexan."""
        discos: dict[Path, Disco] = {}
        pistas: list[Pista] = []
        archivos_por_carpeta: dict[Path, list[Path]] = {}

        raices = self.raices_disponibles()
        for raiz in raices:
            for dirpath, dirnames, filenames in os.walk(raiz):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                carpeta = Path(dirpath)
                if carpeta in archivos_por_carpeta:  # raíz anidada dentro de otra: ya vista
                    continue
                for f in filenames:
                    if f.startswith("."):
                        continue
                    ruta = carpeta / f
                    if ruta.suffix.lower() in EXTENSIONES:
                        archivos_por_carpeta.setdefault(carpeta, []).append(ruta)

        def nombre_de(carpeta: Path) -> str:
            return (carpeta.name or str(carpeta)) if carpeta in raices else carpeta.name

        for carpeta in sorted(archivos_por_carpeta,
                              key=lambda c: (_orden_natural(nombre_de(c)), str(c))):
            nombre = nombre_de(carpeta)
            disco = Disco(id=len(discos), nombre=nombre, ruta=carpeta, norm=normalizar(nombre))
            discos[carpeta] = disco
            for ruta in sorted(archivos_por_carpeta[carpeta], key=lambda r: _orden_natural(r.name)):
                titulo = titulo_desde_archivo(ruta.stem)
                p = Pista(
                    id=len(pistas), disco_id=disco.id, titulo=titulo, ruta=ruta,
                    es_video=ruta.suffix.lower() in EXT_VIDEO, norm=normalizar(titulo),
                )
                pistas.append(p)
                disco.pistas.append(p.id)

        lista_discos = list(discos.values())
        with self._lock:
            self._discos = lista_discos
            self._pistas = pistas
            self._norm_discos = {d.id: d.norm for d in lista_discos}
            self._norm_pistas = {p.id: p.norm for p in pistas}
            self._norm_pistas_con_disco = {
                p.id: f"{lista_discos[p.disco_id].norm} {p.norm}" for p in pistas
            }
        self.listo.set()
        log.info("Índice listo: %d discos, %d pistas", len(lista_discos), len(pistas))

    def raices_disponibles(self, avisar: bool = False) -> list[Path]:
        disponibles = []
        for r in self.raices:
            if r.is_dir():
                disponibles.append(r)
            elif avisar:
                log.warning("No encuentro la carpeta (la salteo): %s", r)
        return disponibles

    def escanear_en_segundo_plano(self) -> None:
        threading.Thread(target=self._escanear_seguro, name="indice", daemon=True).start()

    def _escanear_seguro(self) -> None:
        try:
            self.escanear()
        except Exception:  # noqa: BLE001
            log.exception("Error escaneando la música")

    # ---------- vigilancia de cambios ----------
    def vigilar(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning("watchdog no instalado: no se detectarán cambios en la carpeta.")
            return

        indice = self

        class Manejador(FileSystemEventHandler):
            def on_any_event(self, event):  # noqa: N802
                if event.event_type in {"created", "deleted", "moved", "modified"} and (
                    event.is_directory or Path(event.src_path).suffix.lower() in EXTENSIONES
                ):
                    indice._programar_reescaneo()

        self._observador = Observer()
        for raiz in self.raices_disponibles():
            self._observador.schedule(Manejador(), str(raiz), recursive=True)
        self._observador.daemon = True
        self._observador.start()

    def _programar_reescaneo(self) -> None:
        if self._rescan_timer:
            self._rescan_timer.cancel()
        self._rescan_timer = threading.Timer(5.0, self._escanear_seguro)
        self._rescan_timer.daemon = True
        self._rescan_timer.start()

    def detener(self) -> None:
        if self._observador:
            # En carpetas de red, detener FSEvents puede trabarse: no esperamos más de 2 s.
            hilo = threading.Thread(target=self._observador.stop, daemon=True)
            hilo.start()
            hilo.join(2)
        if self._rescan_timer:
            self._rescan_timer.cancel()

    # ---------- consultas ----------
    @property
    def totales(self) -> dict:
        with self._lock:
            return {"discos": len(self._discos), "pistas": len(self._pistas)}

    def disco(self, disco_id: int) -> Disco | None:
        with self._lock:
            return self._discos[disco_id] if 0 <= disco_id < len(self._discos) else None

    def pista(self, pista_id: int) -> Pista | None:
        with self._lock:
            return self._pistas[pista_id] if 0 <= pista_id < len(self._pistas) else None

    def pistas_de_disco(self, disco_id: int) -> list[Pista]:
        with self._lock:
            if not 0 <= disco_id < len(self._discos):
                return []
            return [self._pistas[i] for i in self._discos[disco_id].pistas]

    def buscar_discos(self, consulta: str, limite: int = 8, minimo: float = 55) -> list[dict]:
        q = normalizar(consulta)
        if not q:
            return []
        with self._lock:
            res = process.extract(q, self._norm_discos, scorer=fuzz.WRatio, limit=limite,
                                  score_cutoff=minimo)
            return [
                {"id": did, "nombre": self._discos[did].nombre,
                 "pistas": len(self._discos[did].pistas), "coincidencia": round(score)}
                for _, score, did in res
            ]

    def buscar_canciones(self, consulta: str, limite: int = 8, minimo: float = 55) -> list[dict]:
        q = normalizar(consulta)
        if not q:
            return []
        with self._lock:
            mejores: dict[int, float] = {}
            for choices, factor in ((self._norm_pistas, 1.0), (self._norm_pistas_con_disco, 0.97)):
                for _, score, pid in process.extract(q, choices, scorer=fuzz.WRatio,
                                                     limit=limite * 3, score_cutoff=minimo):
                    mejores[pid] = max(mejores.get(pid, 0), score * factor)
            orden = sorted(mejores.items(), key=lambda x: -x[1])[:limite]
            return [
                {"id": pid, "titulo": self._pistas[pid].titulo,
                 "disco": self._discos[self._pistas[pid].disco_id].nombre,
                 "video": self._pistas[pid].es_video, "coincidencia": round(score)}
                for pid, score in orden
            ]

    def aleatorio(self, tipo: str) -> list[Pista]:
        with self._lock:
            if not self._pistas:
                return []
            if tipo == "disco":
                d = random.choice(self._discos)
                return [self._pistas[i] for i in d.pistas]
            muestra = random.sample(self._pistas, min(50, len(self._pistas)))
            return muestra
