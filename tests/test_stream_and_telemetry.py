from duo_host.stream import EncodedFrame, LatestFrame
from duo_host.telemetry import Telemetry


def test_latest_frame_wins() -> None:
    queue = LatestFrame()
    queue.put(EncodedFrame(b"old", True))
    queue.put(EncodedFrame(b"new", False))
    assert queue.take() == EncodedFrame(b"new", False)
    assert queue.dropped == 1


def test_telemetry_reports_metrics() -> None:
    telemetry = Telemetry()
    telemetry.record_frame(100, 1_000_000, 2_000_000)
    snapshot = telemetry.snapshot()
    assert snapshot["latency_p50_ms"] == 1
    assert snapshot["latency_p95_ms"] == 1
