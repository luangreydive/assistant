"""Temporizadores locales."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


def formatear_duracion(segundos: float) -> str:
    s = max(0, int(round(segundos)))
    h, resto = divmod(s, 3600)
    m, s = divmod(resto, 60)
    partes = []
    if h:
        partes.append(f"{h} hora" + ("s" if h != 1 else ""))
    if m:
        partes.append(f"{m} minuto" + ("s" if m != 1 else ""))
    if s or not partes:
        partes.append(f"{s} segundo" + ("s" if s != 1 else ""))
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


@dataclass
class Temporizador:
    id: int
    etiqueta: str
    duracion: float
    fin: float
    _timer: threading.Timer = field(repr=False, default=None)

    @property
    def restante(self) -> float:
        return max(0.0, self.fin - time.monotonic())


class Temporizadores:
    def __init__(self, al_terminar: Callable[[Temporizador], None]) -> None:
        self._al_terminar = al_terminar
        self._activos: dict[int, Temporizador] = {}
        self._siguiente_id = 1
        self._lock = threading.Lock()

    def iniciar(self, segundos: float, etiqueta: str = "") -> Temporizador:
        if segundos <= 0:
            raise ValueError("La duración tiene que ser mayor a cero.")
        with self._lock:
            t = Temporizador(id=self._siguiente_id, etiqueta=etiqueta.strip(),
                             duracion=segundos, fin=time.monotonic() + segundos)
            self._siguiente_id += 1
            t._timer = threading.Timer(segundos, self._disparar, args=(t.id,))
            t._timer.daemon = True
            self._activos[t.id] = t
            t._timer.start()
            return t

    def _disparar(self, tid: int) -> None:
        with self._lock:
            t = self._activos.pop(tid, None)
        if t:
            self._al_terminar(t)

    def listar(self) -> list[dict]:
        with self._lock:
            return [
                {"id": t.id, "etiqueta": t.etiqueta or None,
                 "restante": formatear_duracion(t.restante),
                 "restante_segundos": round(t.restante)}
                for t in sorted(self._activos.values(), key=lambda x: x.fin)
            ]

    def cancelar(self, tid: int | None = None, etiqueta: str | None = None,
                 todos: bool = False) -> int:
        with self._lock:
            if todos:
                objetivo = list(self._activos.values())
            elif tid is not None:
                objetivo = [self._activos[tid]] if tid in self._activos else []
            elif etiqueta:
                e = etiqueta.strip().lower()
                objetivo = [t for t in self._activos.values() if e in t.etiqueta.lower()]
            elif len(self._activos) == 1:
                objetivo = list(self._activos.values())
            else:
                objetivo = []
            for t in objetivo:
                t._timer.cancel()
                self._activos.pop(t.id, None)
            return len(objetivo)

    def cancelar_todos(self) -> None:
        self.cancelar(todos=True)
