"""Session orchestration for the Windows host."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
from threading import Event, Thread

from .coordinates import MonitorBounds
from .input import InputEvent, InputInjector
from .monitor import DisplayMode, VirtualMonitor
from .protocol import Codec, Config, Frame, FrameStream, FrameType, Hello, Input, VideoFrame, encode_frame
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
    input_injector: InputInjector | None = None
    _receiver: Thread | None = None
    _receiver_stop: Event | None = None

    def connect(self, transport: ByteTransport, hello: Hello) -> Config:
        codec = (
            Codec.H264
            if Codec.H264 in hello.codecs and shutil.which("ffmpeg")
            else Codec.JPEG
        )
        fps = min(self.max_fps, hello.max_fps)
        requested = DisplayMode(max(hello.width, hello.height), min(hello.width, hello.height), fps)
        actual = self.monitor.start(requested)
        config = Config(codec, actual.width, actual.height, actual.fps)
        self.session = Session.start(transport)
        self.sender = FrameSender(transport)
        self.input_injector = InputInjector(MonitorBounds(0, 0, actual.width, actual.height))
        transport.send(encode_frame(Frame(FrameType.CONFIG, 0, config.encode())))
        self._receiver_stop = Event()
        self._receiver = Thread(
            target=self._receive_loop,
            args=(transport, self._receiver_stop),
            name="duo-input-reader",
            daemon=True,
        )
        self._receiver.start()
        return config

    def _receive_loop(self, transport: ByteTransport, stop: Event) -> None:
        parser = FrameStream()
        try:
            while not stop.is_set() and self.session is not None and self.session.connected:
                data = transport.recv()
                if not data:
                    break
                for frame in parser.feed(data):
                    if frame.message_type == FrameType.INPUT and self.input_injector is not None:
                        event = Input.decode(frame.payload)
                        phases = ("began", "moved", "ended", "cancelled")
                        self.input_injector.inject(
                            InputEvent(
                                event.contact_id,
                                event.x,
                                event.y,
                                phases[event.phase] if event.phase < len(phases) else "cancelled",
                                event.pressure,
                                event.pen,
                            )
                        )
                    else:
                        self.session.receive(frame)
        except OSError:
            if not stop.is_set():
                return

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
        if self._receiver_stop is not None:
            self._receiver_stop.set()
        if self.session is not None:
            self.session.close()
            self.session = None
            self.sender = None
        if self.input_injector is not None:
            self.input_injector.release_all()
            self.input_injector = None
        self.monitor.stop()
