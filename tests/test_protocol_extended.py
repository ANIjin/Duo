from duo_host.protocol import (
    Codec,
    Config,
    Frame,
    FrameStream,
    FrameType,
    Ping,
    VideoFrame,
    encode_frame,
)


def test_stream_parser_accepts_fragmented_frames() -> None:
    wire = encode_frame(Frame(FrameType.PING, 0, Ping(4).encode()))
    parser = FrameStream()
    assert parser.feed(wire[:3]) == []
    assert parser.feed(wire[3:]) == [Frame(FrameType.PING, 0, Ping(4).encode())]


def test_config_and_video_payloads_round_trip() -> None:
    config = Config(Codec.H264, 100, 200, 60, b"sets")
    assert Config.decode(config.encode()) == config
    video = VideoFrame(9, b"image")
    assert VideoFrame.decode(video.encode()) == video
