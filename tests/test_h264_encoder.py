import pytest

from duo_host.stream import EncoderError, FfmpegEncoder, annexb_parameter_sets


def nal_types(data: bytes) -> list[int]:
    types: list[int] = []
    index = 0
    while index + 3 < len(data):
        if data[index : index + 4] == b"\x00\x00\x00\x01":
            types.append(data[index + 4] & 0x1F)
            index += 4
        elif data[index : index + 3] == b"\x00\x00\x01":
            types.append(data[index + 3] & 0x1F)
            index += 3
        else:
            index += 1
    return types


def test_annexb_parameter_sets_from_avcc() -> None:
    sps = b"\x67\x42\x00\x1e"
    pps = b"\x68\xce\x38\x80"
    blob = (
        bytes([1, 0x42, 0, 0x1E, 0xFF, 0xE1])
        + len(sps).to_bytes(2, "big")
        + sps
        + bytes([1])
        + len(pps).to_bytes(2, "big")
        + pps
    )
    assert annexb_parameter_sets(blob) == b"\x00\x00\x00\x01" + sps + b"\x00\x00\x00\x01" + pps
    assert annexb_parameter_sets(b"\x00\x00\x00\x01\x67\x42") == b"\x00\x00\x00\x01\x67\x42"


def test_h264_encoder_emits_idr_with_parameter_sets() -> None:
    pytest.importorskip("av")
    numpy = pytest.importorskip("numpy")
    try:
        encoder = FfmpegEncoder(640, 480, 30, bitrate=2_000_000)
    except EncoderError as error:
        pytest.skip(str(error))
    image = numpy.zeros((480, 640, 3), dtype=numpy.uint8)
    image[:, :, 0] = 32
    frames = []
    try:
        for index in range(6):
            encoded = encoder.encode(image, keyframe=index == 4)
            if encoded is not None:
                frames.append(encoded)
    finally:
        encoder.close()
    assert frames
    keyframes = [frame for frame in frames if frame.keyframe]
    assert keyframes
    assert 7 in nal_types(keyframes[0].data)
    assert 8 in nal_types(keyframes[0].data)
    assert 5 in nal_types(keyframes[0].data)
    assert encoder.parameter_sets
    assert 7 in nal_types(encoder.parameter_sets)
