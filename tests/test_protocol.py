import pytest

from duo_host.protocol import (
    Codec,
    Frame,
    FrameType,
    Hello,
    ProtocolError,
    decode_frame,
    encode_frame,
)


def test_frame_round_trip() -> None:
    original = Frame(FrameType.PING, 0, b"timestamp")
    assert decode_frame(encode_frame(original)) == original


def test_hello_round_trip() -> None:
    original = Hello(2388, 1668, 2.0, 60, (Codec.JPEG, Codec.H264))
    assert Hello.decode(original.encode()) == original


def test_rejects_trailing_bytes() -> None:
    with pytest.raises(ProtocolError, match="exactly one"):
        decode_frame(encode_frame(Frame(FrameType.BYE, 0, b"")) + b"x")


def test_rejects_unknown_message_type() -> None:
    with pytest.raises(ProtocolError, match="unknown frame type"):
        decode_frame(b"\x00\x00\x00\x02\xff\x00")
