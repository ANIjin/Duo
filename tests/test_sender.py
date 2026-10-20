from duo_host.protocol import FrameStream, FrameType, VideoFrame
from duo_host.sender import FrameSender
from duo_host.stream import EncodedFrame


class MemoryTransport:
    def __init__(self) -> None:
        self.data = b""

    def send(self, data: bytes) -> None:
        self.data += data

    def close(self) -> None:
        pass


def test_sender_drops_stale_frames_and_requests_a_real_keyframe() -> None:
    transport = MemoryTransport()
    sender = FrameSender(transport)
    assert sender.force_keyframe is True
    sender.force_keyframe = False
    sender.submit(EncodedFrame(b"first", False), 1)
    sender.submit(EncodedFrame(b"latest", False), 2)
    assert sender.force_keyframe is True
    assert sender.send_latest(2)
    frame = FrameStream().feed(transport.data)[0]
    assert frame.message_type == FrameType.FRAME
    assert frame.flags == 0
    assert VideoFrame.decode(frame.payload).data == b"latest"
