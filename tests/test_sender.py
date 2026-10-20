import time

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


def test_sender_thread_keeps_one_frame_in_flight() -> None:
    class SlowTransport:
        def __init__(self) -> None:
            self.data = b""

        def send(self, data: bytes) -> None:
            time.sleep(0.05)
            self.data += data

        def close(self) -> None:
            return

    transport = SlowTransport()
    sender = FrameSender(transport)
    sender.start()
    try:
        started = time.perf_counter()
        sender.submit(EncodedFrame(b"one", False), 1)
        sender.submit(EncodedFrame(b"two", False), 2)
        elapsed = time.perf_counter() - started
        sender._done.wait(1)
    finally:
        sender.close()
    assert elapsed >= 0.05
    assert b"one" in transport.data
    assert b"two" in transport.data
