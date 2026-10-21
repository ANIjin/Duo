from duo_host.stream import EncodeWindow, EncodedFrame, LatestFrame, next_stream_size
from duo_host.telemetry import Telemetry


def test_latest_frame_wins() -> None:
    queue = LatestFrame()
    queue.put(EncodedFrame(b"old", True))
    queue.put(EncodedFrame(b"new", False))
    assert queue.take() == EncodedFrame(b"new", False)
    assert queue.dropped == 1


def test_next_stream_size_shrinks_when_a_frame_misses_the_budget() -> None:
    assert next_stream_size(2360, 1640, 15.0, 60) is None
    width, height = next_stream_size(2360, 1640, 40.0, 60)
    assert width % 2 == 0 and height % 2 == 0
    # A clear miss jumps to the floor so soft-scaling from a full desktop can
    # get back under a 60 fps budget in one step.
    assert width == 960
    assert abs(width / height - 2360 / 1640) < 0.01
    mild_width, mild_height = next_stream_size(2360, 1640, 18.0, 60)
    assert 960 <= mild_width < 2360
    assert mild_height % 2 == 0
    assert next_stream_size(960, 668, 40.0, 60) is None


def test_encode_window_waits_for_a_second_of_slow_frames() -> None:
    window = EncodeWindow(60)
    window._started = 0.0
    seen = None
    for index in range(8):
        seen = window.observe(40.0, now=2.0 + index * 0.12)
    assert seen == 40.0
    for index in range(30):
        assert window.observe(10.0, now=4.0 + index * 0.02) is None


def test_telemetry_reports_metrics() -> None:
    telemetry = Telemetry()
    telemetry.record_frame(100, 1_000_000, 2_000_000)
    snapshot = telemetry.snapshot()
    assert snapshot["latency_p50_ms"] == 1
    assert snapshot["latency_p95_ms"] == 1
