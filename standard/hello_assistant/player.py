"""Reproductor basado en mpv (reproduce cualquier formato de audio o video).

mpv corre como proceso aparte y se controla por su interfaz JSON IPC
(socket Unix en macOS/Linux, named pipe en Windows). Cada comando abre
su propia conexión: es simple y evita bloqueos de pipes en Windows.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import carpeta_base

log = logging.getLogger(__name__)


class ErrorReproductor(Exception):
    pass


def _buscar_mpv(ruta_config: str | None) -> str:
    candidatos = [ruta_config] if ruta_config else []
    nombre = "mpv.exe" if sys.platform == "win32" else "mpv"
    candidatos += [
        str(carpeta_base() / "bin" / nombre),
        str(carpeta_base() / "bin" / "mpv.app" / "Contents" / "MacOS" / "mpv"),
        shutil.which("mpv") or "",
        "/opt/homebrew/bin/mpv", "/usr/local/bin/mpv",
        "/Applications/mpv.app/Contents/MacOS/mpv",
    ]
    for c in candidatos:
        if c and Path(c).is_file():
            return c
    raise ErrorReproductor(
        "No encontré mpv. En Mac: 'brew install mpv'. En Windows: poné mpv.exe en la "
        "carpeta bin/ del proyecto o indicá MPV_RUTA en el .env."
    )


class Reproductor:
    VOLUMEN_ESCUCHA = 15  # volumen mientras la app te escucha

    def __init__(self, mpv_ruta: str | None, mostrar_video: bool) -> None:
        self._mpv_ruta = mpv_ruta
        self._mostrar_video = mostrar_video
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._req = 0
        self._volumen_previo: float | None = None
        if sys.platform == "win32":
            self._direccion = rf"\\.\pipe\hello-assistant-mpv-{os.getpid()}"
        else:
            self._direccion = f"/tmp/hello-assistant-mpv-{os.getpid()}.sock"

    # ---------- proceso ----------
    def _asegurar(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        mpv = _buscar_mpv(self._mpv_ruta)
        if sys.platform != "win32" and os.path.exists(self._direccion):
            os.unlink(self._direccion)
        args = [
            mpv, "--idle=yes", "--no-terminal", "--force-window=no",
            "--audio-display=no", "--volume=80", "--title=Hello Assistant",
            f"--input-ipc-server={self._direccion}",
        ]
        if not self._mostrar_video:
            args.append("--vid=no")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, creationflags=flags)
        limite = time.time() + 8
        while time.time() < limite:
            try:
                self._enviar_crudo(["get_property", "idle-active"])
                return
            except OSError:
                time.sleep(0.1)
        raise ErrorReproductor("mpv no respondió al iniciar.")

    def cerrar(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._enviar_crudo(["quit"])
                    self._proc.wait(3)
                except Exception:  # noqa: BLE001
                    self._proc.kill()
            self._proc = None

    # ---------- IPC ----------
    def _enviar_crudo(self, comando: list):
        self._req += 1
        req_id = self._req
        datos = (json.dumps({"command": comando, "request_id": req_id}) + "\n").encode()
        if sys.platform == "win32":
            with open(self._direccion, "r+b", buffering=0) as pipe:
                pipe.write(datos)
                return self._leer_respuesta(lambda: pipe.read(1), req_id)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect(self._direccion)
            s.sendall(datos)
            return self._leer_respuesta(lambda: s.recv(1), req_id)

    @staticmethod
    def _leer_respuesta(leer_byte, req_id: int):
        buf = bytearray()
        while True:
            b = leer_byte()
            if not b:
                raise OSError("Conexión cerrada por mpv")
            if b != b"\n":
                buf += b
                continue
            try:
                msg = json.loads(buf.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                msg = {}
            buf.clear()
            if msg.get("request_id") == req_id:
                if msg.get("error") not in (None, "success"):
                    raise ErrorReproductor(msg["error"])
                return msg.get("data")

    def _cmd(self, *comando):
        with self._lock:
            self._asegurar()
            return self._enviar_crudo(list(comando))

    # ---------- acciones ----------
    def reproducir(self, rutas: list[Path]) -> None:
        if not rutas:
            return
        with self._lock:
            self._cmd("loadfile", str(rutas[0]), "replace")
            for r in rutas[1:]:
                self._cmd("loadfile", str(r), "append")
            self._cmd("set_property", "pause", False)

    def pausar(self) -> None:
        self._cmd("set_property", "pause", True)

    def reanudar(self) -> None:
        self._cmd("set_property", "pause", False)

    def siguiente(self) -> None:
        self._cmd("playlist-next", "force")

    def anterior(self) -> None:
        self._cmd("playlist-prev", "force")

    def detener(self) -> None:
        self._cmd("stop")

    def cambiar_volumen(self, delta: int) -> float:
        self._cmd("add", "volume", delta)
        return self._cmd("get_property", "volume")

    def fijar_volumen(self, valor: int) -> None:
        self._cmd("set_property", "volume", max(0, min(130, valor)))

    def estado(self) -> dict:
        if not (self._proc and self._proc.poll() is None):
            return {"reproduciendo": False}
        try:
            idle = self._cmd("get_property", "idle-active")
            if idle:
                return {"reproduciendo": False}
            return {
                "reproduciendo": True,
                "archivo": Path(self._cmd("get_property", "path") or "").name,
                "pausado": bool(self._cmd("get_property", "pause")),
                "volumen": round(self._cmd("get_property", "volume") or 0),
                "posicion_lista": (self._cmd("get_property", "playlist-pos") or 0) + 1,
                "total_lista": self._cmd("get_property", "playlist-count"),
            }
        except (OSError, ErrorReproductor):
            return {"reproduciendo": False}

    # ---------- bajar el volumen mientras escucha (lo usa la etapa de voz) ----------
    def bajar_para_escuchar(self) -> None:
        if not self.estado().get("reproduciendo"):
            return
        with self._lock:
            if self._volumen_previo is None:
                self._volumen_previo = self._cmd("get_property", "volume")
                self._cmd("set_property", "volume", min(self.VOLUMEN_ESCUCHA, self._volumen_previo))

    def restaurar_volumen(self) -> None:
        with self._lock:
            if self._volumen_previo is not None:
                try:
                    self._cmd("set_property", "volume", self._volumen_previo)
                finally:
                    self._volumen_previo = None
