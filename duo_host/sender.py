"""Frame delivery loop with latest-frame-wins backpressure."""

from __future__ import annotations

from threading import Event, Thread
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
        self.error: OSError | None = None
        self._last: EncodedFrame | None = None
        self._last_sent_at = 0.0
        self._timestamp: int | None = None
        self.refresh_interval = 2.0
        self._stop = Event()
        self._wake = Event()
        self._done = Event()
        self._done.set()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(target=self._send_loop, name="duo-sender", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._done.set()
        self._wake.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=0.5)

    def submit(self, encoded: EncodedFrame, capture_timestamp_ns: int | None = None) -> None:
        if self._thread is not None:
            self._done.wait()
            if self._stop.is_set():
                raise OSError("The frame sender is closed")
            if self.error is not None:
                raise self.error
        dropped_before = self.pending.dropped
        self.pending.put(encoded)
        self._last = encoded
        self._timestamp = capture_timestamp_ns
        if self.pending.dropped > dropped_before:
            self.force_keyframe = True
            self.telemetry.dropped_frames = self.pending.dropped
        if self._thread is not None:
            self._done.clear()
            self._wake.set()

    def _send_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.send_latest(self._timestamp)
            except OSError as error:
                self.error = error
            finally:
                self._done.set()

    def send_latest(self, capture_timestamp_ns: int | None = None) -> bool:
        encoded = self.pending.take()
        if encoded is None and self._last is not None:
            if time.monotonic() - self._last_sent_at < self.refresh_interval:
                return False
            encoded = self._last
        if encoded is None:
            return False
        timestamp = time.monotonic_ns() if capture_timestamp_ns is None else capture_timestamp_ns
        flags = FRAME_FLAG_KEYFRAME if encoded.keyframe else 0
        payload = VideoFrame(timestamp, encoded.data).encode()
        self.transport.send(encode_frame(Frame(FrameType.FRAME, flags, payload)))
        self._last_sent_at = time.monotonic()
        self.telemetry.record_frame(len(encoded.data), timestamp)
        return True

    def request_keyframe(self) -> None:
        self.force_keyframe = True
