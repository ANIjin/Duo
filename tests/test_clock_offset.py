from duo_host.telemetry import ClockOffsetEstimator


def test_clock_offset_uses_half_round_trip() -> None:
    estimator = ClockOffsetEstimator()
    assert estimator.observe(100, 160, 120) == 50
