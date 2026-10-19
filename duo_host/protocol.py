"""Versioned length-prefixed protocol shared by the host and iPad client."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import Final

PROTOCOL_VERSION: Final = 1
HEADER = struct.Struct(">IBB")
MAX_PAYLOAD: Final = 64 * 1024 * 1024


class ProtocolError(ValueError):
    """Raised when a wire message is malformed or unsupported."""


class FrameType(IntEnum):
    HELLO = 1
    CONFIG = 2
    FRAME = 3
    INPUT = 4
    PING = 5
    PONG = 6
    BYE = 7
    KEYFRAME_REQ = 8


class Codec(IntEnum):
    JPEG = 1
    H264 = 2


FRAME_FLAG_KEYFRAME: Final = 1


@dataclass(frozen=True, slots=True)
class Frame:
    """One protocol message without its transport framing."""

    message_type: FrameType
    flags: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class Hello:
    """Handshake capabilities exchanged by the host and iPad."""

    width: int
    height: int
    scale: float
    max_fps: int
    codecs: tuple[Codec, ...]

    _HEADER = struct.Struct(">BHHHfB")

    def encode(self) -> bytes:
        if not 1 <= self.width <= 65535 or not 1 <= self.height <= 65535:
            raise ProtocolError("hello dimensions must fit in uint16")
        if not 1 <= self.max_fps <= 65535 or self.scale <= 0:
            raise ProtocolError("hello contains invalid display capabilities")
        codecs = bytes(int(codec) for codec in self.codecs)
        if len(codecs) > 255:
            raise ProtocolError("too many codecs in hello")
        return self._HEADER.pack(
            PROTOCOL_VERSION,
            self.width,
            self.height,
            self.max_fps,
            self.scale,
            len(codecs),
        ) + codecs

    @classmethod
    def decode(cls, payload: bytes) -> Hello:
        if len(payload) < cls._HEADER.size:
            raise ProtocolError("hello payload is truncated")
        version, width, height, max_fps, scale, codec_count = cls._HEADER.unpack_from(payload)
        codecs_raw = payload[cls._HEADER.size :]
        if version != PROTOCOL_VERSION:
            raise ProtocolError(
                f"protocol version mismatch: peer={version}, local={PROTOCOL_VERSION}"
            )
        if len(codecs_raw) != codec_count:
            raise ProtocolError("hello codec list length does not match its count")
        try:
            codecs = tuple(Codec(value) for value in codecs_raw)
        except ValueError as error:
            raise ProtocolError("hello contains an unknown codec") from error
        return cls(width, height, scale, max_fps, codecs)


@dataclass(frozen=True, slots=True)
class Config:
    codec: Codec
    width: int
    height: int
    fps: int
    parameter_sets: bytes = b""

    _HEADER = struct.Struct(">BHHHI")

    def encode(self) -> bytes:
        if min(self.width, self.height, self.fps) <= 0:
            raise ProtocolError("config dimensions and fps must be positive")
        if max(self.width, self.height, self.fps) > 65535:
            raise ProtocolError("config dimensions and fps must fit in uint16")
        return self._HEADER.pack(
            int(self.codec), self.width, self.height, self.fps, len(self.parameter_sets)
        ) + self.parameter_sets

    @classmethod
    def decode(cls, payload: bytes) -> Config:
        if len(payload) < cls._HEADER.size:
            raise ProtocolError("config payload is truncated")
        codec, width, height, fps, parameter_length = cls._HEADER.unpack_from(payload)
        parameter_sets = payload[cls._HEADER.size :]
        if len(parameter_sets) != parameter_length:
            raise ProtocolError("config parameter-set length does not match")
        try:
            return cls(Codec(codec), width, height, fps, parameter_sets)
        except ValueError as error:
            raise ProtocolError("config contains an unknown codec") from error


@dataclass(frozen=True, slots=True)
class VideoFrame:
    timestamp_ns: int
    data: bytes

    _HEADER = struct.Struct(">Q")

    def encode(self) -> bytes:
        return self._HEADER.pack(self.timestamp_ns) + self.data

    @classmethod
    def decode(cls, payload: bytes) -> VideoFrame:
        if len(payload) < cls._HEADER.size:
            raise ProtocolError("video frame is truncated")
        timestamp_ns = cls._HEADER.unpack_from(payload)[0]
        return cls(timestamp_ns, payload[cls._HEADER.size :])


@dataclass(frozen=True, slots=True)
class Ping:
    timestamp_ns: int

    _HEADER = struct.Struct(">Q")

    def encode(self) -> bytes:
        return self._HEADER.pack(self.timestamp_ns)

    @classmethod
    def decode(cls, payload: bytes) -> Ping:
        if len(payload) != cls._HEADER.size:
            raise ProtocolError("ping payload is invalid")
        return cls(cls._HEADER.unpack(payload)[0])


class FrameStream:
    """Incrementally parses frames from a byte stream."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self._buffer.extend(data)
        frames: list[Frame] = []
        while len(self._buffer) >= 4:
            length = struct.unpack_from(">I", self._buffer)[0]
            if length < 2 or length > MAX_PAYLOAD:
                raise ProtocolError("invalid frame length")
            total = 4 + length
            if len(self._buffer) < total:
                break
            frames.append(decode_frame(bytes(self._buffer[:total])))
            del self._buffer[:total]
        return frames


def encode_frame(frame: Frame) -> bytes:
    """Encode a message as ``u32 length | u8 type | u8 flags | payload``."""

    if not 0 <= frame.flags <= 255:
        raise ProtocolError("frame flags must fit in uint8")
    try:
        message_type = FrameType(frame.message_type)
    except ValueError as error:
        raise ProtocolError("unknown frame type") from error
    length = 2 + len(frame.payload)
    if length > MAX_PAYLOAD:
        raise ProtocolError("frame payload exceeds maximum size")
    return struct.pack(">I", length) + bytes((int(message_type), frame.flags)) + frame.payload


def decode_frame(data: bytes) -> Frame:
    """Decode exactly one complete wire message."""

    if len(data) < 6:
        raise ProtocolError("frame is truncated")
    length = struct.unpack_from(">I", data)[0]
    if length < 2 or length > MAX_PAYLOAD:
        raise ProtocolError("invalid frame length")
    if len(data) != 4 + length:
        raise ProtocolError("frame does not contain exactly one message")
    try:
        message_type = FrameType(data[4])
    except ValueError as error:
        raise ProtocolError("unknown frame type") from error
    return Frame(message_type, data[5], data[6:])
