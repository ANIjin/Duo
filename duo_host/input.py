"""Input mapping and Windows injection boundary."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import logging
import sys
import time

from .coordinates import MonitorBounds, map_normalized

LOG = logging.getLogger("duo.input")

MAX_CONTACTS = 10
PT_TOUCH = 2
POINTER_FLAG_INRANGE = 0x00000002
POINTER_FLAG_INCONTACT = 0x00000004
POINTER_FLAG_CANCELED = 0x00008000
POINTER_FLAG_DOWN = 0x00010000
POINTER_FLAG_UPDATE = 0x00020000
POINTER_FLAG_UP = 0x00040000
TOUCH_MASK_CONTACTAREA = 0x00000001
TOUCH_MASK_ORIENTATION = 0x00000002
TOUCH_MASK_PRESSURE = 0x00000004
TOUCH_FEEDBACK_NONE = 3
_HELD = POINTER_FLAG_UPDATE | POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
_MOVE_INTERVAL = 0.008


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _PointerInfo(ctypes.Structure):
    _fields_ = [
        ("pointerType", wintypes.DWORD),
        ("pointerId", wintypes.UINT),
        ("frameId", wintypes.UINT),
        ("pointerFlags", wintypes.DWORD),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", _Point),
        ("ptHimetricLocation", _Point),
        ("ptPixelLocationRaw", _Point),
        ("ptHimetricLocationRaw", _Point),
        ("dwTime", wintypes.DWORD),
        ("historyCount", wintypes.UINT),
        ("inputData", wintypes.INT),
        ("dwKeyStates", wintypes.DWORD),
        ("performanceCount", ctypes.c_uint64),
        ("buttonChangeType", wintypes.INT),
    ]


class PointerTouchInfo(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", _PointerInfo),
        ("touchFlags", wintypes.DWORD),
        ("touchMask", wintypes.DWORD),
        ("rcContact", _Rect),
        ("rcContactRaw", _Rect),
        ("orientation", wintypes.UINT),
        ("pressure", wintypes.UINT),
    ]


@dataclass(frozen=True, slots=True)
class InputEvent:
    contact_id: int
    x: float
    y: float
    phase: str
    pressure: float = 0.0
    pen: bool = False


def contact_rect(x: int, y: int, bounds: MonitorBounds) -> tuple[int, int, int, int]:
    """Keep the contact rectangle inside the monitor. Windows rejects any that leave it."""

    right_edge = bounds.left + bounds.width
    bottom_edge = bounds.top + bounds.height
    left = min(max(bounds.left, x - 2), right_edge - 1)
    top = min(max(bounds.top, y - 2), bottom_edge - 1)
    right = min(max(left + 1, x + 2), right_edge)
    bottom = min(max(top + 1, y + 2), bottom_edge)
    return left, top, right, bottom


class InputInjector:
    def __init__(self, bounds: MonitorBounds) -> None:
        self.bounds = bounds
        self.active_contacts: set[int] = set()
        self.view_only = False
        self._contacts: dict[int, PointerTouchInfo] = {}
        self._slots: dict[int, int] = {}
        self._last_move: dict[int, float] = {}
        self._touch_ready = False
        self._touch_disabled = False
        self._warned_at = 0.0

    def inject(self, event: InputEvent) -> tuple[int, int] | None:
        if self.view_only:
            return None
        point = map_normalized(event.x, event.y, self.bounds)
        if event.phase in {"began", "moved"}:
            self.active_contacts.add(event.contact_id)
        else:
            self.active_contacts.discard(event.contact_id)
        if sys.platform == "win32" and not self._touch_disabled:
            try:
                self._inject_touch(event, point)
            except OSError as error:
                self._recover(error)
                if event.phase not in {"ended", "cancelled"}:
                    retry = InputEvent(
                        event.contact_id,
                        event.x,
                        event.y,
                        "began",
                        event.pressure,
                        event.pen,
                    )
                    try:
                        self._inject_touch(retry, point)
                    except OSError as again:
                        self._recover(again)
        return point

    def _slot(self, contact_id: int) -> int:
        existing = self._slots.get(contact_id)
        if existing is not None:
            return existing
        used = set(self._slots.values())
        for candidate in range(MAX_CONTACTS):
            if candidate not in used:
                self._slots[contact_id] = candidate
                return candidate
        raise OSError("Too many simultaneous touch contacts")

    def _contact(self, pointer_id: int, point: tuple[int, int], flags: int, pressure: float) -> PointerTouchInfo:
        touch = PointerTouchInfo()
        touch.pointerInfo.pointerType = PT_TOUCH
        touch.pointerInfo.pointerId = pointer_id
        touch.pointerInfo.pointerFlags = flags
        touch.pointerInfo.ptPixelLocation = _Point(point[0], point[1])
        touch.touchMask = TOUCH_MASK_CONTACTAREA | TOUCH_MASK_ORIENTATION | TOUCH_MASK_PRESSURE
        touch.orientation = 90
        touch.pressure = max(1, min(1024, int((pressure or 0.5) * 1024)))
        left, top, right, bottom = contact_rect(point[0], point[1], self.bounds)
        touch.rcContact = _Rect(left, top, right, bottom)
        return touch

    def _inject_touch(self, event: InputEvent, point: tuple[int, int]) -> None:
        if event.phase == "moved":
            existing = self._slots.get(event.contact_id)
            if existing is not None and existing in self._contacts:
                if time.monotonic() - self._last_move.get(event.contact_id, 0.0) < _MOVE_INTERVAL:
                    return
        pointer_id = self._slot(event.contact_id)
        lifting = event.phase in {"ended", "cancelled"}
        if lifting and pointer_id not in self._contacts:
            self._slots.pop(event.contact_id, None)
            return
        # Windows rejects a lift unless it is on the same pixel as the last update.
        if lifting:
            last = self._contacts[pointer_id].pointerInfo.ptPixelLocation
            if (last.x, last.y) != point:
                self._emit(pointer_id, point, _HELD, event.pressure)
                self._contacts[pointer_id] = self._contact(pointer_id, point, _HELD, event.pressure)
        if event.phase == "cancelled":
            flags = POINTER_FLAG_UP | POINTER_FLAG_CANCELED
        elif lifting:
            flags = POINTER_FLAG_UP
        elif pointer_id in self._contacts:
            flags = _HELD
        else:
            flags = POINTER_FLAG_DOWN | POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
        self._emit(pointer_id, point, flags, event.pressure)
        if lifting:
            self._contacts.pop(pointer_id, None)
            self._slots.pop(event.contact_id, None)
            self._last_move.pop(event.contact_id, None)
        else:
            self._contacts[pointer_id] = self._contact(pointer_id, point, flags, event.pressure)
            self._last_move[event.contact_id] = time.monotonic()

    def _emit(self, pointer_id: int, point: tuple[int, int], flags: int, pressure: float) -> None:
        touch = self._contact(pointer_id, point, flags, pressure)
        frame: list[PointerTouchInfo] = []
        for other_id, existing in self._contacts.items():
            if other_id == pointer_id:
                continue
            held = PointerTouchInfo.from_buffer_copy(existing)
            held.pointerInfo.pointerFlags = _HELD
            frame.append(held)
        frame.append(touch)
        self._send(frame)

    def _send(self, contacts: list[PointerTouchInfo]) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.InitializeTouchInjection.argtypes = [wintypes.UINT, wintypes.DWORD]
        user32.InitializeTouchInjection.restype = wintypes.BOOL
        user32.InjectTouchInput.argtypes = [wintypes.UINT, ctypes.POINTER(PointerTouchInfo)]
        user32.InjectTouchInput.restype = wintypes.BOOL
        if not self._touch_ready:
            if not user32.InitializeTouchInjection(MAX_CONTACTS, TOUCH_FEEDBACK_NONE):
                self._touch_disabled = True
                raise ctypes.WinError(ctypes.get_last_error())
            self._touch_ready = True
        array = (PointerTouchInfo * len(contacts))(*contacts)
        if not user32.InjectTouchInput(len(contacts), array):
            code = ctypes.get_last_error()
            point = contacts[-1].pointerInfo.ptPixelLocation
            raise OSError(
                f"InjectTouchInput at ({point.x}, {point.y}) on "
                f"{self.bounds.left},{self.bounds.top} "
                f"{self.bounds.width}x{self.bounds.height} failed: {ctypes.WinError(code)}"
            )

    def _recover(self, error: OSError) -> None:
        now = time.monotonic()
        if now - self._warned_at >= 1.0:
            LOG.warning("Touch injection failed: %s", error)
            self._warned_at = now
        self._contacts.clear()
        self._slots.clear()
        self._last_move.clear()
        self.active_contacts.clear()
        self._touch_ready = False
        if sys.platform != "win32" or self._touch_disabled:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.InitializeTouchInjection.argtypes = [wintypes.UINT, wintypes.DWORD]
        user32.InitializeTouchInjection.restype = wintypes.BOOL
        if user32.InitializeTouchInjection(MAX_CONTACTS, TOUCH_FEEDBACK_NONE):
            self._touch_ready = True

    def release_all(self) -> None:
        if sys.platform == "win32" and self._touch_ready and self._contacts and not self._touch_disabled:
            released = []
            for touch in self._contacts.values():
                lift = PointerTouchInfo.from_buffer_copy(touch)
                lift.pointerInfo.pointerFlags = POINTER_FLAG_UP
                released.append(lift)
            try:
                self._send(released)
            except OSError as error:
                LOG.warning("Could not release touch contacts: %s", error)
        self._contacts.clear()
        self._slots.clear()
        self._last_move.clear()
        self.active_contacts.clear()
