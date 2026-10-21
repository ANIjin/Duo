"""Capture, encoding, and latest-frame-wins delivery primitives."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import io
import time
from threading import Lock
from typing import Protocol

from .protocol import Codec


class EncoderError(RuntimeError):
    """Raised when no usable encoder is available."""


def next_stream_size(
    width: int,
    height: int,
    encode_ms: float,
    fps: int,
    floor_width: int = 960,
) -> tuple[int, int] | None:
    """Return a smaller even frame size when encoding misses the frame budget.

    Soft-scaling a full-size capture still has to read every source pixel, so a
    mild shrink does not restore 60 fps. When the frame is clearly late, drop
    straight to the floor size; otherwise take one ~25% step. ``None`` means
    the current size should stay.
    """

    if fps <= 0 or width < 4 or height < 2 or encode_ms <= 0:
        return None
    budget_ms = 1000.0 / fps
    if encode_ms <= budget_ms or width <= floor_width:
        return None
    if encode_ms >= budget_ms * 1.4:
        scale = floor_width / width
    else:
        scale = min(0.75, (budget_ms * 0.85 / encode_ms) ** 0.5)
    new_width = max(floor_width, int(width * scale) // 2 * 2)
    if new_width >= width:
        new_width = max(floor_width, width - (width % 2 or 2))
    if new_width >= width or new_width < 2:
        return None
    new_height = int(round(new_width * height / width))
    new_height -= new_height % 2
    if new_height < 2:
        return None
    return new_width, new_height


class EncodeWindow:
    """Median encode time over the last second, after a short warmup."""

    def __init__(self, fps: int) -> None:
        self.fps = max(int(fps), 1)
        self.samples: deque[tuple[float, float]] = deque()
        self._started = time.monotonic()
        self._hold = False

    def give_up(self) -> None:
        self._hold = True

    def observe(self, encode_ms: float, now: float | None = None) -> float | None:
        if self._hold:
            return None
        current = time.monotonic() if now is None else now
        self.samples.append((current, encode_ms))
        cutoff = current - 1.0
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        if current - self._started < 2.0 or len(self.samples) < 8:
            return None
        if self.samples[-1][0] - self.samples[0][0] < 0.8:
            return None
        ordered = sorted(sample for _, sample in self.samples)
        median = ordered[len(ordered) // 2]
        if median > 1000.0 / self.fps:
            return median
        return None


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
                channels = image[:, :, :3]
                image = Image.fromarray(channels[:, :, ::-1])
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


def parameter_sets_from_annexb(data: bytes) -> bytes:
    """Collect SPS and PPS start-code NALs from an Annex B access unit."""

    nal_units: list[bytes] = []
    index = 0
    length = len(data)
    while index + 3 < length:
        if data[index : index + 4] == b"\x00\x00\x00\x01":
            start = index + 4
        elif data[index : index + 3] == b"\x00\x00\x01":
            start = index + 3
        else:
            index += 1
            continue
        next_index = start
        while next_index + 3 < length and data[next_index : next_index + 3] != b"\x00\x00\x01":
            next_index += 1
        if next_index + 3 >= length:
            next_index = length
        nal = data[start:next_index]
        if nal and (nal[0] & 0x1F) in (7, 8):
            nal_units.append(nal)
        index = next_index
    if not any((nal[0] & 0x1F) == 7 for nal in nal_units):
        return b""
    if not any((nal[0] & 0x1F) == 8 for nal in nal_units):
        return b""
    return b"".join(b"\x00\x00\x00\x01" + nal for nal in nal_units)


class FfmpegEncoder:
    """Low-latency H.264 encoder. Hardware encoders are preferred over x264."""

    codec = Codec.H264
    candidates = ("h264_amf", "h264_nvenc", "h264_qsv", "libx264")

    def __init__(self, width: int, height: int, fps: int, bitrate: int | None = None) -> None:
        if width % 2 or height % 2:
            raise EncoderError(f"H.264 requires even dimensions, got {width}x{height}")
        if fps <= 0:
            raise EncoderError("H.264 fps must be positive")
        if bitrate is None:
            # Keep bits-per-pixel roughly constant as the stream shrinks.
            bitrate = max(4_000_000, int(20_000_000 * (width * height) / (2360 * 1640)))
        if bitrate <= 0:
            raise EncoderError("H.264 bitrate must be positive")
        self.width, self.height, self.fps, self.bitrate = width, height, fps, bitrate
        self._context, self.encoder, self._pix_fmt = self._open()
        self._pts = 0
        self._bgra = None
        self._scaler = None
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
            for pix_fmt, options in self._variants(name, self.fps):
                context = av.CodecContext.create(name, "w")
                context.width = self.width
                context.height = self.height
                context.pix_fmt = pix_fmt
                context.framerate = Fraction(self.fps, 1)
                context.time_base = Fraction(1, self.fps)
                context.bit_rate = self.bitrate
                context.gop_size = max(self.fps, 1)
                context.max_b_frames = 0
                context.options = options
                try:
                    context.open()
                except Exception as error:
                    failures.append(f"{name}/{pix_fmt}: {error}")
                    continue
                return context, name, pix_fmt
        detail = "; ".join(failures) if failures else "no encoders were compiled in"
        raise EncoderError(f"No usable H.264 encoder. {detail}")

    @staticmethod
    def _variants(name: str, fps: int) -> tuple[tuple[str, dict[str, str]], ...]:
        if name == "h264_qsv":
            # Quick Sync rejects yuv420p here and only accepts nv12. async_depth
            # above 1 queues frames in the driver; after a few seconds that queue
            # stops draining and every encode call blocks for hundreds of milliseconds.
            # Prefer low_power first: on Iris Xe it finishes faster under load.
            return (
                ("nv12", {"preset": "veryfast", "async_depth": "1", "low_power": "1"}),
                ("nv12", {"preset": "veryfast", "async_depth": "1"}),
            )
        if name == "h264_amf":
            return (("bgra", FfmpegEncoder._options(name, fps)),)
        return (("yuv420p", FfmpegEncoder._options(name, fps)),)

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

    def _downscale(self, array):
        """Shrink a larger capture before the NV12 convert.

        FFmpeg swscale from a full 2360x1640 frame stays expensive even when the
        output is small, because it still reads every source pixel. Nearest
        neighbor through Pillow is faster here and keeps the virtual display at
        the iPad's native layout.
        """

        import numpy as np
        from PIL import Image

        if (
            array.shape[0] == self.height * 2
            and array.shape[1] == self.width * 2
        ):
            return np.ascontiguousarray(array[::2, ::2])
        mode = "RGBA" if array.shape[2] == 4 else "RGB"
        if mode == "RGB" and array.shape[2] == 3:
            # Capture is BGR; Pillow wants RGB. Swap for the resize only.
            image = Image.fromarray(array[:, :, ::-1], mode)
            resized = image.resize((self.width, self.height), Image.Resampling.NEAREST)
            return np.ascontiguousarray(np.asarray(resized)[:, :, ::-1])
        image = Image.fromarray(array, mode)
        resized = image.resize((self.width, self.height), Image.Resampling.NEAREST)
        return np.ascontiguousarray(np.asarray(resized))

    def encode(self, image, keyframe: bool = False) -> EncodedFrame | None:
        import numpy as np

        array = np.asarray(image)
        if array.ndim != 3 or array.shape[2] not in (3, 4):
            raise EncoderError("H.264 encoder requires an HxWx3 BGR or HxWx4 BGRA capture array")
        import av

        array = np.ascontiguousarray(array)
        if self._pix_fmt == "nv12":
            source_format = "bgra" if array.shape[2] == 4 else "bgr24"
            if array.shape[0] < self.height or array.shape[1] < self.width:
                raise EncoderError(
                    f"Capture is {array.shape[1]}x{array.shape[0]} but the H.264 encoder is "
                    f"{self.width}x{self.height}"
                )
            if array.shape[0] != self.height or array.shape[1] != self.width:
                array = self._downscale(array)
                source_format = "bgra" if array.shape[2] == 4 else "bgr24"
            # Fast bilinear is the cheapest filtered chroma downsample.
            frame = av.VideoFrame.from_ndarray(array, format=source_format).reformat(
                format="nv12",
                interpolation="FAST_BILINEAR",
            )
        elif self.encoder == "h264_amf":
            if array.shape[2] == 3:
                if self._bgra is None or self._bgra.shape[0] != array.shape[0] or self._bgra.shape[1] != array.shape[1]:
                    self._bgra = np.empty((array.shape[0], array.shape[1], 4), dtype=np.uint8)
                    self._bgra[:, :, 3] = 255
                self._bgra[:, :, :3] = array
                frame = av.VideoFrame.from_ndarray(self._bgra, format="bgra")
            else:
                frame = av.VideoFrame.from_ndarray(array, format="bgra")
        else:
            if array.shape[0] != self.height or array.shape[1] != self.width:
                raise EncoderError(
                    f"Capture is {array.shape[1]}x{array.shape[0]} but the H.264 encoder is "
                    f"{self.width}x{self.height}"
                )
            if array.shape[2] == 4:
                array = np.ascontiguousarray(array[:, :, :3])
            frame = av.VideoFrame.from_ndarray(array, format="bgr24")
        frame.pts = self._pts
        self._pts += 1
        if keyframe:
            frame.pict_type = av.video.frame.PictureType.I
        try:
            packets = self._context.encode(frame)
        except av.FFmpegError as error:
            raise EncoderError(f"H.264 encoder {self.encoder} failed: {error}") from error
        if not packets:
            return None
        data = b"".join(bytes(packet) for packet in packets)
        if not self.parameter_sets:
            self.parameter_sets = annexb_parameter_sets(bytes(self._context.extradata or b""))
        if not self.parameter_sets:
            # libx264 leaves extradata empty unless a global header is requested,
            # but repeat-headers still puts SPS and PPS on the keyframe.
            self.parameter_sets = parameter_sets_from_annexb(data)
        return EncodedFrame(data, any(bool(packet.is_keyframe) for packet in packets))

    def close(self) -> None:
        context = self._context
        self._context = None
        # AMF's flush can block forever after a stalled submit. Quick Sync
        # needs the flush so the driver releases the session on the way out.
        if context is not None and self.encoder == "h264_qsv":
            try:
                context.encode(None)
            except Exception:
                return
