"""Capture, encoding, and latest-frame-wins delivery primitives."""

from __future__ import annotations

from dataclasses import dataclass
import io
from threading import Lock
from typing import Protocol

from .protocol import Codec


class EncoderError(RuntimeError):
    """Raised when no usable encoder is available."""


class FrameSource(Protocol):
    def frames(self): ...


@dataclass(frozen=True, slots=True)
class EncodedFrame:
    data: bytes
    keyframe: bool


class LatestFrame:
    """A one-slot buffer: replacing a frame explicitly counts a drop."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._frame: EncodedFrame | None = None
        self.dropped = 0

    def put(self, frame: EncodedFrame) -> None:
        with self._lock:
            if self._frame is not None:
                self.dropped += 1
            self._frame = frame

    def take(self) -> EncodedFrame | None:
        with self._lock:
            frame, self._frame = self._frame, None
            return frame


class JpegEncoder:
    codec = Codec.JPEG

    def __init__(self, quality: int = 40) -> None:
        if not 20 <= quality <= 95:
            raise ValueError("JPEG quality must be between 20 and 95")
        self.quality = quality

    def encode(self, image, keyframe: bool = False) -> EncodedFrame:
        try:
            from PIL import Image
        except ImportError as error:
            raise EncoderError("JPEG capture requires Pillow") from error
        if not isinstance(image, Image.Image):
            try:
                image = Image.fromarray(image[:, :, ::-1])
            except (AttributeError, TypeError, ValueError) as error:
                raise EncoderError("JPEG encoder requires a Pillow Image or BGR array") from error
        output = io.BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=self.quality,
            subsampling=2,
            optimize=False,
            progressive=False,
        )
        return EncodedFrame(output.getvalue(), True)


def annexb_parameter_sets(extradata: bytes) -> bytes:
    """Return Annex B SPS/PPS bytes from Annex B or AVCC encoder extradata."""

    if extradata.startswith((b"\x00\x00\x00\x01", b"\x00\x00\x01")):
        return extradata
    if not extradata or extradata[0] != 1 or len(extradata) < 7:
        return b""
    offset = 5
    nal_count = extradata[offset] & 0x1F
    offset += 1
    nal_units: list[bytes] = []
    for _ in range(nal_count):
        if offset + 2 > len(extradata):
            return b""
        length = int.from_bytes(extradata[offset : offset + 2], "big")
        offset += 2
        if length <= 0 or offset + length > len(extradata):
            return b""
        nal_units.append(extradata[offset : offset + length])
        offset += length
    if offset >= len(extradata):
        return b""
    nal_count = extradata[offset]
    offset += 1
    for _ in range(nal_count):
        if offset + 2 > len(extradata):
            return b""
        length = int.from_bytes(extradata[offset : offset + 2], "big")
        offset += 2
        if length <= 0 or offset + length > len(extradata):
            return b""
        nal_units.append(extradata[offset : offset + length])
        offset += length
    return b"".join(b"\x00\x00\x00\x01" + nal for nal in nal_units)


class FfmpegEncoder:
    """Low-latency H.264 encoder. Hardware encoders are preferred over x264."""

    codec = Codec.H264
    candidates = ("h264_amf", "h264_nvenc", "h264_qsv", "libx264")

    def __init__(self, width: int, height: int, fps: int, bitrate: int = 20_000_000) -> None:
        if width % 2 or height % 2:
            raise EncoderError(f"H.264 requires even dimensions, got {width}x{height}")
        if fps <= 0 or bitrate <= 0:
            raise EncoderError("H.264 fps and bitrate must be positive")
        self.width, self.height, self.fps, self.bitrate = width, height, fps, bitrate
        self._context, self.encoder = self._open()
        self._pts = 0
        self.parameter_sets = annexb_parameter_sets(bytes(self._context.extradata or b""))

    def _open(self):
        try:
            import av
            from fractions import Fraction
        except ImportError as error:
            raise EncoderError(
                "H.264 encoding requires PyAV. Install it with "
                'python -m pip install -e ".[runtime]", then restart Duo.'
            ) from error
        failures: list[str] = []
        for name in self.candidates:
            context = av.CodecContext.create(name, "w")
            context.width = self.width
            context.height = self.height
            context.pix_fmt = "yuv420p"
            context.framerate = Fraction(self.fps, 1)
            context.time_base = Fraction(1, self.fps)
            context.bit_rate = self.bitrate
            context.gop_size = max(self.fps, 1)
            context.max_b_frames = 0
            context.options = self._options(name, self.fps)
            try:
                context.open()
            except Exception as error:
                failures.append(f"{name}: {error}")
                continue
            return context, name
        detail = "; ".join(failures) if failures else "no encoders were compiled in"
        raise EncoderError(f"No usable H.264 encoder. {detail}")

    @staticmethod
    def _options(name: str, fps: int) -> dict[str, str]:
        if name == "h264_amf":
            return {
                "usage": "ultralowlatency",
                "rc": "cbr",
                "quality": "speed",
                "async_depth": "1",
                "forced_idr": "1",
                "aud": "1",
                "bf": "0",
                "profile": "main",
                "level": "5.1",
                "preanalysis": "0",
                "latency": "1",
                # Intra refresh paints a new frame in bands over the old one.
                "intra_refresh_mb": "0",
                "frame_skipping": "0",
                "header_spacing": str(max(fps, 1)),
            }
        if name == "h264_nvenc":
            return {
                "preset": "p1",
                "tune": "ull",
                "rc": "cbr",
                "delay": "0",
                "zerolatency": "1",
                "forced-idr": "1",
                "bf": "0",
                "aud": "1",
                "profile": "main",
                "level": "5.1",
            }
        if name == "h264_qsv":
            return {
                "preset": "veryfast",
                "look_ahead": "0",
                "bf": "0",
                "async_depth": "1",
                "profile": "main",
                "level": "5.1",
            }
        return {
            "preset": "ultrafast",
            "tune": "zerolatency",
            "bf": "0",
            "profile": "main",
            "level": "5.1",
            "x264-params": "repeat-headers=1:aud=1:scenecut=0",
        }

    @property
    def warning(self) -> str | None:
        return "Using software x264; latency may be higher" if self.encoder == "libx264" else None

    def encode(self, image, keyframe: bool = False) -> EncodedFrame | None:
        import numpy as np

        array = np.asarray(image)
        if array.ndim != 3 or array.shape[2] != 3:
            raise EncoderError("H.264 encoder requires an HxWx3 BGR capture array")
        if array.shape[0] != self.height or array.shape[1] != self.width:
            raise EncoderError(
                f"Capture is {array.shape[1]}x{array.shape[0]} but the H.264 encoder is "
                f"{self.width}x{self.height}"
            )
        import av

        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(array), format="bgr24")
        frame.pts = self._pts
        self._pts += 1
        if keyframe:
            frame.pict_type = av.video.frame.PictureType.I
        try:
            packets = self._context.encode(frame)
        except av.FFmpegError as error:
            raise EncoderError(f"H.264 encoder {self.encoder} failed: {error}") from error
        if not self.parameter_sets:
            self.parameter_sets = annexb_parameter_sets(bytes(self._context.extradata or b""))
        if not packets:
            return None
        data = b"".join(bytes(packet) for packet in packets)
        return EncodedFrame(data, any(bool(packet.is_keyframe) for packet in packets))

    def close(self) -> None:
        # Drop the context without flushing. AMF's flush call can block forever
        # after a stalled submit, which would keep the host from reconnecting.
        self._context = None
