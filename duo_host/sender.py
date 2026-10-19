"""Frame delivery loop with latest-frame-wins backpressure."""

from __future__ import annotations

import time

from .protocol import FRAME_FLAG_KEYFRAME, Frame, FrameType, VideoFrame, encode_frame
from .stream import EncodedFrame, LatestFrame
from .telemetry import Telemetry
from .transport import ByteTransport


class FrameSender:
    def __init__(self, transport: ByteTransport) -> None:
        self.transport = transport
        self.pending = LatestFrame()
        self.telemetry = Telemetry()
        self.force_keyframe = True
        self._last: EncodedFrame | None = None
        self._last_sent_at = 0.0
        self.refresh_interval = 2.0

    def submit(self, encoded: EncodedFrame, capture_timestamp_ns: int | None = None) -> None:
        if self.force_keyframe:
            encoded = EncodedFrame(encoded.data, True)
            self.force_keyframe = False
        self.pending.put(encoded)
        self._last = encoded
        if self.pending.dropped:
            self.force_keyframe = True
            self.telemetry.dropped_frames = self.pending.dropped

    def send_latest(self, capture_timestamp_ns: int | None = None) -> bool:
        encoded = self.pending.take()
        if encoded is None and self._last is not None:
            if time.monotonic() - self._last_sent_at < self.refresh_interval:
                return False
            encoded = self._last
        if encoded is None:
            return False
        if self.force_keyframe:
            encoded = EncodedFrame(encoded.data, True)
            self.force_keyframe = False
        timestamp = time.monotonic_ns() if capture_timestamp_ns is None else capture_timestamp_ns
        flags = FRAME_FLAG_KEYFRAME if encoded.keyframe else 0
        payload = VideoFrame(timestamp, encoded.data).encode()
        self.transport.send(encode_frame(Frame(FrameType.FRAME, flags, payload)))
        self._last_sent_at = time.monotonic()
        self.telemetry.record_frame(len(encoded.data), timestamp)
        return True

    def request_keyframe(self) -> None:
        self.force_keyframe = True
