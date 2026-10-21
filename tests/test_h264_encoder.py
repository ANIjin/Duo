import pytest

from duo_host.stream import EncoderError, FfmpegEncoder, annexb_parameter_sets, parameter_sets_from_annexb


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


def test_parameter_sets_from_annexb_keeps_sps_and_pps() -> None:
    access_unit = b"\x00\x00\x00\x01\x67\x42\x00\x01\x00\x00\x00\x01\x68\xce\x00\x00\x00\x01\x65\xff"
    sets = parameter_sets_from_annexb(access_unit)
    assert nal_types(sets) == [7, 8]
    assert parameter_sets_from_annexb(b"\x00\x00\x00\x01\x65\xff") == b""


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


def test_h264_encoder_scales_a_larger_capture() -> None:
    pytest.importorskip("av")
    numpy = pytest.importorskip("numpy")
    try:
        encoder = FfmpegEncoder(320, 240, 30, bitrate=1_000_000)
    except EncoderError as error:
        pytest.skip(str(error))
    if encoder._pix_fmt != "nv12":
        encoder.close()
        pytest.skip("capture scaling is implemented for the nv12 encoder")
    image = numpy.zeros((480, 640, 4), dtype=numpy.uint8)
    encoded = None
    try:
        for _ in range(4):
            encoded = encoder.encode(image, keyframe=True)
            if encoded is not None:
                break
    finally:
        encoder.close()
    assert encoded is not None
    assert encoded.data
