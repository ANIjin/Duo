"""Coordinate conversion for input sent by the iPad."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MonitorBounds:
    left: int
    top: int
    width: int
    height: int


def map_normalized(x: float, y: float, bounds: MonitorBounds) -> tuple[int, int]:
    """Map normalized video coordinates into only the virtual monitor bounds."""

    if not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ValueError("input coordinates must be normalized to 0..1")
    if bounds.width <= 0 or bounds.height <= 0:
        raise ValueError("monitor bounds must have positive dimensions")
    return (
        bounds.left + round(x * (bounds.width - 1)),
        bounds.top + round(y * (bounds.height - 1)),
    )
