"""Capture, encoding, and latest-frame-wins delivery primitives."""

from __future__ import annotations

from dataclasses import dataclass
import io
import queue
import shutil
import subprocess
from threading import Lock, Thread
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

    def encode(self, image) -> EncodedFrame:
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


class FfmpegEncoder:
    """Persistent low-latency H.264 encoder using the first available FFmpeg encoder."""

    codec = Codec.H264
    candidates = ("h264_amf", "h264_nvenc", "h264_qsv", "libx264")

    def __init__(self, width: int, height: int, fps: int) -> None:
        if shutil.which("ffmpeg") is None:
            raise EncoderError("FFmpeg is required for H.264 encoding")
        self.width, self.height, self.fps = width, height, fps
        self.encoder = self._select_encoder()
        encoder_options = {
            "h264_amf": ["-usage", "ultralowlatency", "-quality", "speed", "-b:v", "20M"],
            "h264_nvenc": ["-preset", "p1", "-tune", "ull", "-rc", "cbr", "-b:v", "20M"],
            "h264_qsv": ["-preset", "veryfast", "-look_ahead", "0", "-b:v", "20M"],
            "libx264": ["-preset", "ultrafast", "-tune", "zerolatency"],
        }[self.encoder]
        self._process = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
                "-an", "-c:v", self.encoder, *encoder_options, "-bf", "0", "-g", str(fps),
                "-pix_fmt", "yuv420p", "-bsf:v", "h264_metadata=aud=insert",
                "-f", "h264", "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._output = queue.Queue()
        self._buffer = bytearray()
        self._access_unit = bytearray()
        self._reader = Thread(target=self._read_output, daemon=True, name="duo-h264-reader")
        self._reader.start()

    @staticmethod
    def _start_code(data: bytes, offset: int = 0) -> int:
        for index in range(offset, len(data) - 3):
            if data[index:index + 4] == b"\x00\x00\x00\x01":
                return index
            if data[index:index + 3] == b"\x00\x00\x01":
                return index
        return -1

    @staticmethod
    def _nal_type(nal: bytes) -> int:
        prefix = 4 if nal.startswith(b"\x00\x00\x00\x01") else 3
        return nal[prefix] & 0x1F

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        while True:
            chunk = self._process.stdout.read(64 * 1024)
            if not chunk:
                return
            self._buffer.extend(chunk)
            starts = []
            offset = 0
            while True:
                start = self._start_code(self._buffer, offset)
                if start < 0:
                    break
                starts.append(start)
                offset = start + 3
            if len(starts) < 2:
                continue
            for start, end in zip(starts, starts[1:]):
                nal = bytes(self._buffer[start:end])
                if len(nal) > 4 and self._nal_type(nal) == 9:
                    if self._access_unit:
                        self._output.put(self._access_unit)
                    self._access_unit = bytearray(nal)
                else:
                    self._access_unit.extend(nal)
            del self._buffer[:starts[-1]]

    def _next_access_unit(self) -> bytes:
        try:
            return self._output.get(timeout=2)
        except queue.Empty as error:
            raise EncoderError("FFmpeg did not produce an H.264 access unit") from error

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

    def encode(self, image, keyframe: bool = False) -> EncodedFrame:
        try:
            raw = image.tobytes()
        except AttributeError as error:
            raise EncoderError("H.264 encoder requires a BGR capture array") from error
        if self._process.stdin is None:
            raise EncoderError("H.264 encoder input is unavailable")
        try:
            self._process.stdin.write(raw)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise EncoderError("FFmpeg H.264 encoder stopped") from error
        return EncodedFrame(self._next_access_unit(), keyframe)

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        self._process.terminate()
