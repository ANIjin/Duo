from duo_host.coordinates import MonitorBounds
from duo_host.input import InputInjector, contact_rect


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
