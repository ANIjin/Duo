"""Virtual monitor and capture adapters.

The actual IddCx driver remains an external dependency. Keeping this boundary
explicit prevents the host from silently capturing the primary display.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import logging
import struct
import subprocess
from ctypes import wintypes

from .coordinates import MonitorBounds

LOG = logging.getLogger("duo.monitor")

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2. Touch injection uses the same
# pixels as the captured frame only after the process opts into this.
_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


def use_physical_screen_coordinates() -> None:
    """Make monitor rectangles and touch injection use physical pixels."""

    if not hasattr(ctypes, "WinDLL"):
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    if user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2):
        return
    error = ctypes.get_last_error()
    user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.AreDpiAwarenessContextsEqual.restype = wintypes.BOOL
    current = user32.GetThreadDpiAwarenessContext()
    if not user32.AreDpiAwarenessContextsEqual(current, _PER_MONITOR_AWARE_V2):
        LOG.warning(
            "Could not enable physical screen coordinates (WinError %s). "
            "Touches can land on the laptop screen.",
            error,
        )


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


def _place_virtual_mode(device_name: str, width: int, height: int, fps: int) -> None:
    """Extend ``device_name`` onto the desktop at ``width`` x ``height``.

    ChangeDisplaySettingsEx fails for this indirect display. The display
    configuration API can place it to the right of the existing desktop.
    """

    class _Luid(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

    class _Source(ctypes.Structure):
        _fields_ = [
            ("adapter", _Luid),
            ("id", wintypes.UINT),
            ("mode_index", wintypes.UINT),
            ("status", wintypes.UINT),
        ]

    class _Rational(ctypes.Structure):
        _fields_ = [("numerator", wintypes.UINT), ("denominator", wintypes.UINT)]

    class _Target(ctypes.Structure):
        _fields_ = [
            ("adapter", _Luid),
            ("id", wintypes.UINT),
            ("mode_index", wintypes.UINT),
            ("technology", wintypes.INT),
            ("rotation", wintypes.UINT),
            ("scaling", wintypes.UINT),
            ("refresh", _Rational),
            ("scan_line", wintypes.UINT),
            ("available", wintypes.BOOL),
            ("status", wintypes.UINT),
        ]

    class _Path(ctypes.Structure):
        _fields_ = [("source", _Source), ("target", _Target), ("flags", wintypes.UINT)]

    class _Mode(ctypes.Structure):
        _fields_ = [
            ("info_type", wintypes.UINT),
            ("id", wintypes.UINT),
            ("adapter", _Luid),
            ("data", ctypes.c_ubyte * 48),
        ]

    class _SourceName(ctypes.Structure):
        _fields_ = [
            ("kind", wintypes.UINT),
            ("size", wintypes.UINT),
            ("adapter", _Luid),
            ("id", wintypes.UINT),
            ("name", wintypes.WCHAR * 32),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetDisplayConfigBufferSizes.restype = ctypes.c_long
    user32.QueryDisplayConfig.restype = ctypes.c_long
    user32.SetDisplayConfig.restype = ctypes.c_long
    user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
    user32.DisplayConfigGetDeviceInfo.restype = ctypes.c_long
    user32.QueryDisplayConfig.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(_Path),
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(_Mode),
        ctypes.POINTER(wintypes.UINT),
    ]
    user32.SetDisplayConfig.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(_Path),
        wintypes.UINT,
        ctypes.POINTER(_Mode),
        wintypes.UINT,
    ]

    def query(flags: int) -> tuple[ctypes.Array, ctypes.Array]:
        path_count = wintypes.UINT()
        mode_count = wintypes.UINT()
        status = user32.GetDisplayConfigBufferSizes(flags, ctypes.byref(path_count), ctypes.byref(mode_count))
        if status != 0:
            raise MonitorError(f"Could not read the Windows display topology (error {status})")
        paths = (_Path * path_count.value)()
        modes = (_Mode * mode_count.value)()
        status = user32.QueryDisplayConfig(
            flags, ctypes.byref(path_count), paths, ctypes.byref(mode_count), modes, None
        )
        if status != 0:
            raise MonitorError(f"Could not query the Windows display topology (error {status})")
        return paths[: path_count.value], modes[: mode_count.value]

    def source_name(path: _Path) -> str:
        info = _SourceName()
        info.kind = 1
        info.size = ctypes.sizeof(_SourceName)
        info.adapter = path.source.adapter
        info.id = path.source.id
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(info)) != 0:
            return ""
        return str(info.name)

    active_paths, active_modes = query(0x12)
    paths = list(active_paths)
    modes = list(active_modes)
    target = device_name.casefold()
    selected = next((path for path in paths if source_name(path).casefold() == target), None)
    if selected is None:
        all_paths, all_modes = query(0x11)
        modes = list(all_modes)
        selected = next((path for path in all_paths if source_name(path).casefold() == target), None)
        if selected is None:
            raise MonitorError(f"Windows has no display path for {device_name}")
        selected.flags |= 0x9
        paths.append(selected)

    def source_index(path: _Path) -> int:
        return (int(path.source.mode_index) >> 16) & 0xFFFF

    def read_source(mode: _Mode) -> tuple[int, int, int, int, int]:
        return struct.unpack_from("<IIIii", bytes(mode.data))

    def write_source(mode: _Mode, geometry: tuple[int, int, int, int, int]) -> None:
        raw = bytearray(mode.data)
        struct.pack_into("<IIIii", raw, 0, *geometry)
        mode.data = (ctypes.c_ubyte * 48).from_buffer_copy(bytes(raw))

    right_edge = 0
    for path in paths:
        if path is selected:
            continue
        index = source_index(path)
        if index == 0xFFFF or index >= len(modes) or modes[index].info_type != 1:
            continue
        mode_width, _height, _pixel, origin, _top = read_source(modes[index])
        right_edge = max(right_edge, origin + mode_width)

    index = source_index(selected)
    if index == 0xFFFF or index >= len(modes) or modes[index].info_type != 1:
        created = _Mode()
        created.info_type = 1
        modes.append(created)
        index = len(modes) - 1
        selected.source.mode_index = (index << 16) | 0xFFFF
    _width, _height, pixel_format, _origin, _top = read_source(modes[index])
    write_source(modes[index], (width, height, pixel_format or 4, right_edge, 0))
    selected.target.mode_index = (int(selected.target.mode_index) & 0xFFFF0000) | 0xFFFF
    selected.target.refresh.numerator = max(1, fps)
    selected.target.refresh.denominator = 1
    selected.flags |= 0x9
    path_array = (_Path * len(paths))(*paths)
    mode_array = (_Mode * len(modes))(*modes)
    flags = 0x20 | 0x80 | 0x200 | 0x400 | 0x8000
    status = user32.SetDisplayConfig(len(paths), path_array, len(modes), mode_array, flags)
    if status != 0:
        raise MonitorError(
            f"Windows could not extend {device_name} to {width}x{height}@{fps} "
            f"(SetDisplayConfig error {status})"
        )
    LOG.info("Extended %s to %sx%s at desktop x=%s", device_name, width, height, right_edge)


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
        if (
            user32.EnumDisplaySettingsW(found, -1, ctypes.byref(current))
            and int(current.dmPelsWidth) == mode.width
            and int(current.dmPelsHeight) == mode.height
            and int(current.dmDisplayFrequency or mode.fps) == mode.fps
            and _screen_rect(self.device_name) is not None
        ):
            return DisplayMode(
                mode.width,
                mode.height,
                int(current.dmDisplayFrequency or mode.fps),
                int(current.dmPositionX),
                int(current.dmPositionY),
            )

        supported: list[DisplayMode] = []
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
                    )
                )
            mode_index += 1
        chosen = mode
        if supported and not any(
            item.width == mode.width and item.height == mode.height and item.fps == mode.fps
            for item in supported
        ):
            requested_aspect = mode.width / mode.height
            same_aspect = [
                item for item in supported
                if abs(item.width / item.height - requested_aspect) <= 0.01
            ]
            chosen = min(
                same_aspect or supported,
                key=lambda item: (
                    abs(item.width * item.height - mode.width * mode.height),
                    abs(item.fps - mode.fps),
                ),
            )
            LOG.warning(
                "Driver has no %sx%s@%s mode; extending %sx%s@%s",
                mode.width, mode.height, mode.fps,
                chosen.width, chosen.height, chosen.fps,
            )
        _place_virtual_mode(self.device_name, chosen.width, chosen.height, chosen.fps)
        placed = DevMode()
        placed.dmSize = ctypes.sizeof(DevMode)
        if not user32.EnumDisplaySettingsW(found, -1, ctypes.byref(placed)):
            raise MonitorError(f"{self.device_name} did not become an active display")
        return DisplayMode(
            int(placed.dmPelsWidth),
            int(placed.dmPelsHeight),
            int(placed.dmDisplayFrequency or chosen.fps),
            int(placed.dmPositionX),
            int(placed.dmPositionY),
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


def _dxcam_output_index(device_name: str) -> int | None:
    import dxcam

    target = device_name.casefold()
    for outputs in dxcam.__factory.outputs:
        for index, output in enumerate(outputs):
            if str(output.devicename).casefold() == target:
                return index
    return None


class DxcamCapture:
    def __init__(self, monitor_index: int, device_name: str | None = None) -> None:
        self.monitor_index = monitor_index
        try:
            import dxcam
        except ImportError as error:
            raise MonitorError("Install dxcam to capture the virtual monitor") from error
        output_index = _dxcam_output_index(device_name) if device_name else None
        if output_index is None:
            output_index = monitor_index
        try:
            self._camera = dxcam.create(output_idx=output_index, output_color="BGR")
        except IndexError as error:
            raise MonitorError(
                f"Virtual display {device_name or output_index} is not on the desktop, "
                "so there is no screen to capture."
            ) from error

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
