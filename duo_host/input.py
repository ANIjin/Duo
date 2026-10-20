"""Input mapping and Windows injection boundary."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import sys

from .coordinates import MonitorBounds, map_normalized


@dataclass(frozen=True, slots=True)
class InputEvent:
    contact_id: int
    x: float
    y: float
    phase: str
    pressure: float = 0.0
    pen: bool = False


class InputInjector:
    def __init__(self, bounds: MonitorBounds) -> None:
        self.bounds = bounds
        self.active_contacts: set[int] = set()
        self.view_only = False

    def inject(self, event: InputEvent) -> tuple[int, int] | None:
        if self.view_only:
            return None
        point = map_normalized(event.x, event.y, self.bounds)
        if event.phase in {"began", "moved"}:
            self.active_contacts.add(event.contact_id)
        elif event.phase == "ended":
            self.active_contacts.discard(event.contact_id)
        if sys.platform == "win32" and not event.pen:
            self._inject_touch(event, point)
        return point

    def _inject_touch(self, event: InputEvent, point: tuple[int, int]) -> None:
        class TouchInput(ctypes.Structure):
            _fields_ = [
                ("x", ctypes.c_long),
                ("y", ctypes.c_long),
                ("contact", ctypes.c_void_p),
                ("flags", ctypes.c_ulong),
                ("mask", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("extra", ctypes.c_ulonglong),
                ("orientation", ctypes.c_ulong),
                ("pressure", ctypes.c_ulong),
            ]

        user32 = ctypes.windll.user32
        if not hasattr(self, "_touch_initialized"):
            if not user32.InitializeTouchInjection(10, 1):
                raise OSError(ctypes.get_last_error(), "InitializeTouchInjection failed")
            self._touch_initialized = True
        flags = {"began": 0x0002, "moved": 0x0001, "ended": 0x0004}.get(event.phase, 0x0008)
        touch = TouchInput(
            point[0] * 100,
            point[1] * 100,
            event.contact_id,
            flags,
            0x0001 | 0x0002 | 0x0004 | 0x0008,
            0,
            0,
            90,
            int(event.pressure * 1024),
        )
        if not user32.InjectTouchInput(1, ctypes.byref(touch)):
            raise OSError(ctypes.get_last_error(), "InjectTouchInput failed")

    def release_all(self) -> None:
        self.active_contacts.clear()
