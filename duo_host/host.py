"""Session orchestration for the Windows host."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from threading import Event, Lock, Thread

from .input import InputEvent, InputInjector
from .monitor import DisplayMode, VirtualMonitor
from .protocol import (
    Codec,
    Config,
    Frame,
    FrameStream,
    FrameType,
    Hello,
    Input,
    ProtocolError,
    encode_frame,
)
from .session import Session
from .stream import EncodedFrame, EncoderError
from .sender import FrameSender
from .transport import ByteTransport

LOG = logging.getLogger("duo")


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
    _io_lock: Lock = field(default_factory=Lock)
    _send_lock: Lock = field(default_factory=Lock)

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
        self.session = Session.start(transport)
        self.sender = FrameSender(transport)
        self.sender.start()
        self._receiver_stop = Event()
        self._receiver = Thread(
            target=self._receive_loop,
            args=(transport, self._receiver_stop),
            name="duo-input-reader",
            daemon=True,
        )
        self._receiver.start()
        Thread(
            target=self._heartbeat_loop,
            args=(self._receiver_stop,),
            name="duo-heartbeat",
            daemon=True,
        ).start()
        actual = self.monitor.start(requested)
        config = Config(codec, actual.width, actual.height, actual.fps)
        self._config = config
        touch_bounds = self.monitor.input_bounds()
        LOG.info(
            "Touch target %sx%s at %s,%s",
            touch_bounds.width,
            touch_bounds.height,
            touch_bounds.left,
            touch_bounds.top,
        )
        self.input_injector = InputInjector(touch_bounds)
        with self._send_lock:
            transport.send(encode_frame(Frame(FrameType.CONFIG, 0, config.encode())))
        return config

    @property
    def connected(self) -> bool:
        session = self.session
        return session is not None and session.connected

    def _heartbeat_loop(self, stop: Event) -> None:
        while not stop.wait(0.25):
            self.tick()

    def announce_parameter_sets(self, parameter_sets: bytes) -> None:
        if not parameter_sets:
            return
        with self._send_lock:
            with self._io_lock:
                if self.session is None or self._config is None:
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
                payload = encode_frame(Frame(FrameType.CONFIG, 0, self._config.encode()))
                transport = self.session.transport
            transport.send(payload)

    def consume_keyframe_request(self) -> bool:
        with self._io_lock:
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
                        try:
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
                        except (OSError, ValueError) as error:
                            LOG.warning("Touch injection failed: %s", error)
                    else:
                        with self._send_lock:
                            if self.session is not None:
                                self.session.receive(frame)
        except (OSError, ProtocolError) as error:
            if not stop.is_set():
                self.disconnect(f"iPad input channel ended: {error}")
                return

    def send_frame(self, frame: EncodedFrame, capture_timestamp_ns: int | None = None) -> bool:
        with self._io_lock:
            if self.session is None or self.sender is None:
                return False
            sender = self.sender
        sender.submit(frame, capture_timestamp_ns)
        return True

    def tick(self) -> None:
        with self._io_lock:
            session = self.session
            expired = session is not None and session.is_expired()
        if session is None:
            return
        if expired:
            self.disconnect("iPad link lost: no data received for 2 seconds.")
            return
        with self._send_lock:
            with self._io_lock:
                current = self.session
            if current is not None and current.connected and not current.is_expired():
                try:
                    current.heartbeat()
                except OSError as error:
                    self.disconnect(f"iPad link lost: {error}")

    def disconnect(self, reason: str | None = None) -> None:
        with self._io_lock:
            if self._receiver_stop is not None:
                self._receiver_stop.set()
            session = self.session
            sender = self.sender
            self.session = None
            self.sender = None
            self._config = None
            injector = self.input_injector
            self.input_injector = None
        if session is not None and reason:
            LOG.warning("%s", reason)
        if sender is not None:
            sender.close()
        if injector is not None:
            injector.release_all()
        if session is not None:
            session.close()
        self.monitor.stop()
