"""Evita que la computadora se duerma mientras la app está abierta.

La pantalla SÍ puede apagarse; solo se impide la suspensión del sistema.
- macOS: `caffeinate -i -w <pid>` (se corta solo si la app muere).
- Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading

log = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


class MantenerDespierta:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()

    def iniciar(self) -> bool:
        if sys.platform == "darwin":
            return self._iniciar_mac()
        if sys.platform == "win32":
            return self._iniciar_windows()
        if shutil.which("systemd-inhibit"):
            self._proc = subprocess.Popen(
                ["systemd-inhibit", "--what=sleep:idle", "--who=Hello Assistant",
                 "--why=App abierta", "sleep", "infinity"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        log.warning("No sé cómo evitar la suspensión en este sistema.")
        return False

    def _iniciar_mac(self) -> bool:
        # -i: impide la suspensión por inactividad. -w: termina cuando muere este proceso.
        self._proc = subprocess.Popen(
            ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True

    def _iniciar_windows(self) -> bool:
        import ctypes

        listo = threading.Event()
        ok = {"valor": False}

        def trabajar() -> None:
            # El estado se asocia al hilo: lo mantenemos vivo hasta parar().
            k32 = ctypes.windll.kernel32
            ok["valor"] = bool(k32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED))
            listo.set()
            self._parar.wait()
            k32.SetThreadExecutionState(_ES_CONTINUOUS)

        self._hilo = threading.Thread(target=trabajar, name="mantener-despierta", daemon=True)
        self._hilo.start()
        listo.wait(5)
        return ok["valor"]

    def detener(self) -> None:
        self._parar.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
