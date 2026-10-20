"""Virtual monitor and capture adapters.

The actual IddCx driver remains an external dependency. Keeping this boundary
explicit prevents the host from silently capturing the primary display.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import logging
import subprocess
from ctypes import wintypes

from .coordinates import MonitorBounds

LOG = logging.getLogger("duo.monitor")


class MonitorError(RuntimeError):
    """Raised when the configured virtual display driver is unavailable."""


@dataclass(frozen=True, slots=True)
class DisplayMode:
    width: int
    height: int
    fps: int
    left: int = 0
    top: int = 0


def _screen_rect(device_name: str) -> MonitorBounds | None:
    """Monitor rectangle in this process's coordinate space, or None."""

    if not device_name or not hasattr(ctypes, "windll"):
        return None

    class _Rect(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class _MonitorInfoEx(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", _Rect),
            ("rcWork", _Rect),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(_Rect),
        wintypes.LPARAM,
    )
    found: dict[str, tuple[int, int, int, int]] = {}
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfoEx)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    def _visit(monitor, hdc, rect, data):
        info = _MonitorInfoEx()
        info.cbSize = ctypes.sizeof(_MonitorInfoEx)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            box = info.rcMonitor
            found[str(info.szDevice)] = (int(box.left), int(box.top), int(box.right - box.left), int(box.bottom - box.top))
        return True

    callback = callback_type(_visit)
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(_Rect), callback_type, wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        return None
    target = device_name.casefold()
    for name, (left, top, width, height) in found.items():
        if name.casefold() == target and width > 0 and height > 0:
            return MonitorBounds(left, top, width, height)
    return None


class VirtualMonitor:
    def __init__(self, driver_name: str = "IddSampleDriver") -> None:
        self.driver_name = driver_name
        self.mode: DisplayMode | None = None
        self.device_name: str | None = None
        self.started = False

    def ensure_driver(self) -> None:
        if ctypes.windll.user32.EnumDisplayDevicesW is None:
            raise MonitorError("Windows display APIs are unavailable")
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_PnPSignedDriver | "
                "Where-Object { $_.DeviceClass -eq 'DISPLAY' } | "
                "Select-Object DeviceName,DriverProviderName | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or self.driver_name.lower() not in result.stdout.lower():
            raise MonitorError(
                f"Virtual display driver '{self.driver_name}' is missing. "
                "Install the signed IddCx virtual display driver before starting."
            )

    def start(self, mode: DisplayMode) -> None:
        self.ensure_driver()
        self.mode = self._apply_mode(mode)
        self.started = True
        return self.mode

    def _apply_mode(self, mode: DisplayMode) -> DisplayMode:
        """Request the negotiated mode from the Windows display driver."""
        if not hasattr(ctypes, "windll"):
            return mode

        class DisplayDevice(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128),
            ]

        class DevMode(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", wintypes.WCHAR * 32),
                ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD),
                ("dmPositionX", wintypes.LONG),
                ("dmPositionY", wintypes.LONG),
                ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", wintypes.SHORT),
                ("dmDuplex", wintypes.SHORT),
                ("dmYResolution", wintypes.SHORT),
                ("dmTTOption", wintypes.SHORT),
                ("dmCollate", wintypes.SHORT),
                ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD),
                ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD),
                ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD),
                ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD),
                ("dmMediaType", wintypes.DWORD),
                ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD),
                ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD),
                ("dmPanningHeight", wintypes.DWORD),
            ]

        display = DisplayDevice()
        display.cb = ctypes.sizeof(DisplayDevice)
        user32 = ctypes.windll.user32
        found = None
        for index in range(16):
            if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(display), 0):
                break
            if self.driver_name.lower() in display.DeviceString.lower():
                found = display.DeviceName
                break
            display = DisplayDevice()
            display.cb = ctypes.sizeof(DisplayDevice)
        if found is None:
            raise MonitorError(f"Could not locate display device for '{self.driver_name}'")
        self.device_name = str(found)

        current = DevMode()
        current.dmSize = ctypes.sizeof(DevMode)
        if user32.EnumDisplaySettingsW(found, -1, ctypes.byref(current)):
            current_fps = int(current.dmDisplayFrequency or mode.fps)
            if (
                int(current.dmPelsWidth) == mode.width
                and int(current.dmPelsHeight) == mode.height
                and current_fps == mode.fps
            ):
                return DisplayMode(
                    mode.width,
                    mode.height,
                    current_fps,
                    int(current.dmPositionX),
                    int(current.dmPositionY),
                )

        devmode = DevMode()
        devmode.dmSize = ctypes.sizeof(DevMode)
        devmode.dmFields = 0x00080000 | 0x00100000 | 0x00400000
        devmode.dmPelsWidth = mode.width
        devmode.dmPelsHeight = mode.height
        devmode.dmDisplayFrequency = mode.fps
        result = user32.ChangeDisplaySettingsExW(found, ctypes.byref(devmode), None, 0, None)
        if result != 0:
            current = DevMode()
            current.dmSize = ctypes.sizeof(DevMode)
            current_mode = None
            if user32.EnumDisplaySettingsW(found, -1, ctypes.byref(current)):
                current_mode = DisplayMode(
                    int(current.dmPelsWidth),
                    int(current.dmPelsHeight),
                    int(current.dmDisplayFrequency or mode.fps),
                    int(current.dmPositionX),
                    int(current.dmPositionY),
                )
            supported = []
            mode_index = 0
            while True:
                candidate = DevMode()
                candidate.dmSize = ctypes.sizeof(DevMode)
                if not user32.EnumDisplaySettingsW(found, mode_index, ctypes.byref(candidate)):
                    break
                if candidate.dmPelsWidth and candidate.dmPelsHeight:
                    supported.append(
                        DisplayMode(
                            int(candidate.dmPelsWidth),
                            int(candidate.dmPelsHeight),
                            int(candidate.dmDisplayFrequency or mode.fps),
                            int(candidate.dmPositionX),
                            int(candidate.dmPositionY),
                        )
                    )
                mode_index += 1
            if supported and current_mode is not None:
                requested_aspect = mode.width / mode.height
                current_aspect = current_mode.width / current_mode.height
                if abs(current_aspect - requested_aspect) <= 0.12:
                    LOG.warning(
                        "Driver rejected %sx%s@%s; using current mode %sx%s@%s",
                        mode.width, mode.height, mode.fps,
                        current_mode.width, current_mode.height, current_mode.fps,
                    )
                    return current_mode
            if supported:
                requested_aspect = mode.width / mode.height
                same_aspect = [
                    candidate for candidate in supported
                    if abs(candidate.width / candidate.height - requested_aspect) <= 0.01
                ]
                candidates = same_aspect or supported
                fallback = min(
                    candidates,
                    key=lambda candidate: (
                        abs(candidate.width * candidate.height - mode.width * mode.height),
                        abs(candidate.fps - mode.fps),
                    ),
                )
                LOG.warning(
                    "Driver rejected %sx%s@%s; using supported mode %sx%s@%s",
                    mode.width, mode.height, mode.fps,
                    fallback.width, fallback.height, fallback.fps,
                )
                return fallback
            raise MonitorError(
                f"Virtual display driver rejected {mode.width}x{mode.height}@{mode.fps} Hz "
                f"(ChangeDisplaySettingsEx result {result})"
            )
        return DisplayMode(
            mode.width,
            mode.height,
            mode.fps,
            int(current.dmPositionX),
            int(current.dmPositionY),
        )

    def input_bounds(self) -> MonitorBounds:
        """Return the virtual monitor rectangle in this process's screen coordinates.

        Touch injection uses the same coordinate space as ``GetMonitorInfo``.
        That rectangle can be smaller than the captured mode when Windows is
        scaling the display.
        """

        rect = _screen_rect(self.device_name) if self.device_name else None
        if rect is not None:
            return rect
        LOG.warning("Touch could not find monitor %s; using the display mode origin.", self.device_name)
        mode = self.mode
        if mode is None:
            return MonitorBounds(0, 0, 1, 1)
        return MonitorBounds(mode.left, mode.top, mode.width, mode.height)

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

    def close(self) -> None:
        camera = self._camera
        self._camera = None
        if camera is None:
            return
        try:
            camera.release()
        except Exception:
            return
