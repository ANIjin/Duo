"""Session orchestration for the Windows host."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

from .coordinates import MonitorBounds
from .input import InputEvent, InputInjector
from .monitor import DisplayMode, VirtualMonitor
from .protocol import Codec, Config, Frame, FrameStream, FrameType, Hello, Input, VideoFrame, encode_frame
from .session import Session
from .stream import EncodedFrame, EncoderError
from .sender import FrameSender
from .transport import ByteTransport


@dataclass(slots=True)
class HostController:
    monitor: VirtualMonitor
    max_fps: int = 60
    codec_preference: str = "h264"
    session: Session | None = None
    sender: FrameSender | None = None
    input_injector: InputInjector | None = None
    _receiver: Thread | None = None
    _receiver_stop: Event | None = None
    _config: Config | None = None

    def connect(self, transport: ByteTransport, hello: Hello) -> Config:
        if self.codec_preference == "jpeg":
            codec = Codec.JPEG
        elif Codec.H264 in hello.codecs:
            codec = Codec.H264
        elif self.codec_preference == "h264":
            raise EncoderError(
                "The iPad client does not advertise H.264. Rebuild and sideload the latest app, "
                "or start the host with --codec jpeg."
            )
        else:
            codec = Codec.JPEG
        fps = min(self.max_fps, hello.max_fps)
        requested = DisplayMode(max(hello.width, hello.height), min(hello.width, hello.height), fps)
        actual = self.monitor.start(requested)
        config = Config(codec, actual.width, actual.height, actual.fps)
        self._config = config
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

    def announce_parameter_sets(self, parameter_sets: bytes) -> None:
        if self.session is None or self._config is None or not parameter_sets:
            return
        if self._config.parameter_sets == parameter_sets:
            return
        self._config = Config(
            self._config.codec,
            self._config.width,
            self._config.height,
            self._config.fps,
            parameter_sets,
        )
        self.session.transport.send(encode_frame(Frame(FrameType.CONFIG, 0, self._config.encode())))

    def consume_keyframe_request(self) -> bool:
        requested = False
        if self.session is not None and self.session.keyframe_requested:
            self.session.keyframe_requested = False
            requested = True
        if self.sender is not None and self.sender.force_keyframe:
            self.sender.force_keyframe = False
            requested = True
        return requested

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
            self._config = None
        if self.input_injector is not None:
            self.input_injector.release_all()
            self.input_injector = None
        self.monitor.stop()
