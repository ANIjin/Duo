"""Session orchestration for the Windows host."""

from __future__ import annotations

from dataclasses import dataclass

from .monitor import DisplayMode, VirtualMonitor
from .protocol import Codec, Config, Frame, FrameType, Hello, VideoFrame, encode_frame
from .session import Session
from .stream import EncodedFrame
from .sender import FrameSender
from .transport import ByteTransport


@dataclass(slots=True)
class HostController:
    monitor: VirtualMonitor
    max_fps: int = 60
    session: Session | None = None
    sender: FrameSender | None = None

    def connect(self, transport: ByteTransport, hello: Hello) -> Config:
        codec = Codec.JPEG if Codec.JPEG in hello.codecs else Codec.H264
        fps = min(self.max_fps, hello.max_fps)
        self.monitor.start(DisplayMode(hello.width, hello.height, fps))
        config = Config(codec, hello.width, hello.height, fps)
        self.session = Session.start(transport)
        self.sender = FrameSender(transport)
        transport.send(encode_frame(Frame(FrameType.CONFIG, 0, config.encode())))
        return config

    def send_frame(self, frame: EncodedFrame, capture_timestamp_ns: int | None = None) -> bool:
        if self.session is None or self.sender is None:
            return False
        if self.session.keyframe_requested:
            self.sender.request_keyframe()
            self.session.keyframe_requested = False
        self.sender.submit(frame, capture_timestamp_ns)
        return self.sender.send_latest(capture_timestamp_ns)

    def tick(self) -> None:
        if self.session is None:
            return
        if self.session.is_expired():
            self.disconnect()
            return
        self.session.heartbeat()

    def disconnect(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
            self.sender = None
        self.monitor.stop()
