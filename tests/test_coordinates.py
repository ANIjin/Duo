import pytest

from duo_host.coordinates import MonitorBounds, map_normalized


def test_maps_to_monitor_origin_and_end() -> None:
    bounds = MonitorBounds(-1920, 0, 1920, 1080)
    assert map_normalized(0, 0, bounds) == (-1920, 0)
    assert map_normalized(1, 1, bounds) == (-1, 1079)


def test_rejects_coordinates_outside_video() -> None:
    with pytest.raises(ValueError):
        map_normalized(1.01, 0.5, MonitorBounds(0, 0, 100, 100))
