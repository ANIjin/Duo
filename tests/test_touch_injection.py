import time

from duo_host.coordinates import MonitorBounds
from duo_host.input import (
    POINTER_FLAG_DOWN,
    POINTER_FLAG_UP,
    POINTER_FLAG_UPDATE,
    InputEvent,
    InputInjector,
    contact_rect,
)


def test_large_contact_ids_use_pointer_slots_windows_accepts() -> None:
    injector = InputInjector(MonitorBounds(0, 0, 1920, 1080))
    first = injector._slot(50000)
    second = injector._slot(12)
    assert first == injector._slot(50000)
    assert 0 <= first < 10
    assert 0 <= second < 10
    assert first != second


def test_contact_rect_stays_inside_the_monitor() -> None:
    bounds = MonitorBounds(-1180, -25, 1180, 820)
    assert contact_rect(-1180, -25, bounds) == (-1180, -25, -1178, -23)
    left, top, right, bottom = contact_rect(-591, 385, bounds)
    assert bounds.left <= left < right <= bounds.left + bounds.width
    assert bounds.top <= top < bottom <= bounds.top + bounds.height


def test_moves_closer_than_the_interval_are_not_injected() -> None:
    injector = InputInjector(MonitorBounds(2560, 0, 2360, 1640))
    sent: list[int] = []
    injector._send = sent.append  # type: ignore[method-assign]
    injector.inject(InputEvent(1, 0.2, 0.2, "began"))
    injector._last_move[1] = time.monotonic()
    injector.inject(InputEvent(1, 0.8, 0.8, "moved"))
    assert len(sent) == 1
    injector._last_move[1] = time.monotonic() - 1
    injector.inject(InputEvent(1, 0.9, 0.9, "moved"))
    assert len(sent) == 2


def test_a_failed_injection_is_retried_as_a_new_press() -> None:
    injector = InputInjector(MonitorBounds(2560, 0, 2360, 1640))
    flags: list[int] = []

    def send(frame: list) -> None:
        flags.append(frame[-1].pointerInfo.pointerFlags)
        if len(flags) == 1:
            raise OSError("InjectTouchInput failed")

    injector._send = send  # type: ignore[method-assign]
    injector._recover = lambda error: (  # type: ignore[method-assign]
        injector._contacts.clear(),
        injector._slots.clear(),
        injector._last_move.clear(),
    )
    injector.inject(InputEvent(7, 0.4, 0.4, "moved"))
    assert flags[0] & POINTER_FLAG_DOWN
    assert flags[1] & POINTER_FLAG_DOWN
    assert injector._contacts


def test_a_lift_at_a_new_point_updates_that_point_first() -> None:
    injector = InputInjector(MonitorBounds(2560, 0, 2360, 1640))
    sent: list[int] = []
    injector._send = lambda frame: sent.append(frame[-1].pointerInfo.pointerFlags)  # type: ignore[method-assign]
    injector.inject(InputEvent(1, 0.2, 0.2, "began"))
    injector.inject(InputEvent(1, 0.8, 0.8, "ended"))
    assert sent[0] & POINTER_FLAG_DOWN
    assert sent[1] & POINTER_FLAG_UPDATE
    assert sent[2] & POINTER_FLAG_UP
    assert not injector._contacts
