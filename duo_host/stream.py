"""Capture, encoding, and latest-frame-wins delivery primitives."""

from __future__ import annotations

from dataclasses import dataclass
import io
import shutil
import subprocess
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

    def encode(self, image) -> EncodedFrame:
        try:
            from PIL import Image
        except ImportError as error:
            raise EncoderError("JPEG capture requires Pillow") from error
        if not isinstance(image, Image.Image):
            raise EncoderError("JPEG encoder requires a Pillow Image")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=80, optimize=False)
        return EncodedFrame(output.getvalue(), True)


class FfmpegEncoder:
    """Low-latency H.264 adapter using the first available FFmpeg encoder."""

    codec = Codec.H264
    candidates = ("h264_amf", "h264_nvenc", "h264_qsv", "libx264")

    def __init__(self, width: int, height: int, fps: int) -> None:
        if shutil.which("ffmpeg") is None:
            raise EncoderError("FFmpeg is required for H.264 encoding")
        self.width, self.height, self.fps = width, height, fps
        self.encoder = self._select_encoder()

    def _select_encoder(self) -> str:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
        )
        available = result.stdout
        for encoder in self.candidates:
            if encoder in available:
                return encoder
        raise EncoderError("No H.264 encoder found; install FFmpeg with AMF, NVENC, QSV, or x264")

    @property
    def warning(self) -> str | None:
        return "Using software x264; latency may be higher" if self.encoder == "libx264" else None

    def encode(self, raw_bgra: bytes, keyframe: bool = False) -> EncodedFrame:
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps), "-i", "pipe:0", "-an", "-c:v", self.encoder,
            "-bf", "0", "-tune", "zerolatency", "-f", "h264", "pipe:1",
        ]
        result = subprocess.run(command, input=raw_bgra, capture_output=True, check=False)
        if result.returncode:
            raise EncoderError(result.stderr.decode(errors="replace"))
        return EncodedFrame(result.stdout, keyframe)
