"""Host session lifecycle primitives.

The concrete usbmux and Windows display-driver adapters are intentionally
injected so protocol behavior can be tested without hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Protocol

from .protocol import Frame, FrameType, Hello, Ping, ProtocolError, encode_frame
from .transport import ByteTransport


@dataclass(slots=True)
class Session:
    transport: ByteTransport
    last_rx: float
    connected: bool = True
    last_ping: float = 0.0
    keyframe_requested: bool = False

    @classmethod
    def start(cls, transport: ByteTransport) -> Session:
        return cls(transport=transport, last_rx=time.monotonic())

    def receive_hello(self, payload: bytes) -> Hello:
        hello = Hello.decode(payload)
        self.last_rx = time.monotonic()
        return hello

    def receive(self, frame: Frame) -> None:
        if not self.connected:
            raise ProtocolError("received data on a closed session")
        self.last_rx = time.monotonic()
        if frame.message_type == FrameType.PING:
            self.transport.send(encode_frame(Frame(FrameType.PONG, 0, frame.payload)))
        elif frame.message_type == FrameType.KEYFRAME_REQ:
            self.keyframe_requested = True
        if frame.message_type == FrameType.BYE:
            self.close()

    def heartbeat(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        if current - self.last_ping >= 0.5:
            self.transport.send(
                encode_frame(
                    Frame(FrameType.PING, 0, Ping(time.monotonic_ns()).encode())
                )
            )
            self.last_ping = current

    def is_expired(self, now: float | None = None, timeout: float = 2.0) -> bool:
        if not self.connected:
            return True
        current = time.monotonic() if now is None else now
        return current - self.last_rx > timeout

    def close(self) -> None:
        if self.connected:
            self.connected = False
            self.transport.close()
