"""Low-overhead stream and latency metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
import statistics
import time


@dataclass(slots=True)
class Telemetry:
    started_at: float = field(default_factory=time.monotonic)
    frames: int = 0
    bytes_sent: int = 0
    dropped_frames: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def record_frame(self, size: int, capture_timestamp_ns: int, now_ns: int | None = None) -> None:
        self.frames += 1
        self.bytes_sent += size
        current = time.monotonic_ns() if now_ns is None else now_ns
        self.latencies_ms.append(max(0.0, (current - capture_timestamp_ns) / 1_000_000))
        if len(self.latencies_ms) > 10_000:
            del self.latencies_ms[:1_000]

    def snapshot(self) -> dict[str, float | int]:
        values = sorted(self.latencies_ms)
        p50 = statistics.quantiles(values, n=100)[49] if len(values) >= 2 else (values[0] if values else 0.0)
        p95 = statistics.quantiles(values, n=100)[94] if len(values) >= 2 else (values[0] if values else 0.0)
        elapsed = max(time.monotonic() - self.started_at, 0.001)
        return {
            "fps": self.frames / elapsed,
            "bitrate_bps": self.bytes_sent * 8 / elapsed,
            "dropped_frames": self.dropped_frames,
            "latency_p50_ms": p50,
            "latency_p95_ms": p95,
        }


@dataclass(slots=True)
class ClockOffsetEstimator:
    """NTP-style estimate where timestamps are monotonic nanoseconds."""

    offset_ns: int = 0

    def observe(self, sent_ns: int, peer_received_ns: int, received_ns: int) -> int:
        round_trip = received_ns - sent_ns
        self.offset_ns = peer_received_ns - (sent_ns + round_trip // 2)
        return self.offset_ns
