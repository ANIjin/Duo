"""Input mapping and Windows injection boundary."""

from __future__ import annotations

from dataclasses import dataclass

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
        # ctypes SendInput/InitializeTouchInjection is wired here on Windows.
        return point

    def release_all(self) -> None:
        self.active_contacts.clear()
