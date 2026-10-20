import pytest

from duo_host.stream import JpegEncoder


def test_jpeg_quality_is_bounded() -> None:
    assert JpegEncoder(65).quality == 65
    with pytest.raises(ValueError):
        JpegEncoder(10)
