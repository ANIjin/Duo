"""Virtual monitor and capture adapters.

The actual IddCx driver remains an external dependency. Keeping this boundary
explicit prevents the host from silently capturing the primary display.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import subprocess


class MonitorError(RuntimeError):
    """Raised when the configured virtual display driver is unavailable."""


@dataclass(frozen=True, slots=True)
class DisplayMode:
    width: int
    height: int
    fps: int


class VirtualMonitor:
    def __init__(self, driver_name: str = "IddSampleDriver") -> None:
        self.driver_name = driver_name
        self.mode: DisplayMode | None = None
        self.started = False

    def ensure_driver(self) -> None:
        if ctypes.windll.user32.EnumDisplayDevicesW is None:
            raise MonitorError("Windows display APIs are unavailable")
        # Driver enumeration is performed by the installed driver package.
        result = subprocess.run(
            ["pnputil", "/enum-drivers"], capture_output=True, text=True, check=False
        )
        if self.driver_name.lower() not in result.stdout.lower():
            raise MonitorError(
                f"Virtual display driver '{self.driver_name}' is missing. "
                "Install the signed IddCx virtual display driver before starting."
            )

    def start(self, mode: DisplayMode) -> None:
        self.ensure_driver()
        self.mode = mode
        self.started = True

    def stop(self) -> None:
        self.started = False
        self.mode = None


class DxcamCapture:
    def __init__(self, monitor_index: int) -> None:
        self.monitor_index = monitor_index
        try:
            import dxcam
        except ImportError as error:
            raise MonitorError("Install dxcam to capture the virtual monitor") from error
        self._camera = dxcam.create(output_idx=monitor_index, output_color="BGR")

    def frames(self, target_fps: int = 60):
        self._camera.start(target_fps=target_fps, video_mode=True)
        try:
            while True:
                frame = self._camera.get_latest_frame()
                if frame is not None:
                    yield frame
        finally:
            self._camera.stop()
