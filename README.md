# Duo

Duo is an experimental wired USB second-display project for Windows and iPadOS entirely built with artificial intelligence.
This project was driven by the irritation caused by paywalls for simple python-based software that works natively on many devices outside the Apple ecosystem.

## Feasibility target

Duo is meant to work on any Windows 10/11 laptop and any iPad with a USB-C or
Lightning cable. The host picks a hardware H.264 encoder when the GPU provides
one (`h264_amf`, `h264_nvenc`, or `h264_qsv`) and otherwise uses `libx264`.
The iPad app reports its own pixel size during the handshake.

The host keeps the driver, capture, usbmux, and encoder integrations behind
explicit adapters so protocol tests can run without an attached iPad.

## Development

The host prototype targets Python 3.11+. Install development dependencies and run
the protocol tests with:

```powershell
python -m pip install -e ".[dev,runtime]"
python -m pytest
```

The iPad client source is under `ipad/`. It is intended to be opened in Xcode
on macOS for signing and device testing.

## Device installation

These steps are the same on any Windows laptop. The iPad app has to be a build
that listens on localhost. An older build listens on Wi-Fi only. The iPad is
attached and Duo can be open, but usbmux still gets "connection refused" on
port 24862. Reinstall the current app after pulling these client changes.

1. Install a signed IddCx virtual display driver and confirm a second monitor
   appears in Windows Display settings. The host looks for a driver named
   `Virtual Display Driver` unless you pass `--driver-name`.
2. Install Apple Devices or iTunes so Apple Mobile Device Support and usbmux
   are available. Unlock the iPad, connect the cable, and tap Trust. Developer
   Mode must be on for a sideloaded app. Confirm the iPad is visible:

   ```powershell
   python -c "from pymobiledevice3.usbmux import list_devices; import asyncio; print(asyncio.run(list_devices()))"
   ```

3. Install the host package with the runtime extra, then start the host:

   ```powershell
   python -m duo_host
   ```

   The default driver name is `Virtual Display Driver` (MikeTheTech's driver).
   Use `--driver-name` if a different IddCx driver is installed.
   Capture uses the desktop's BGRA buffer, so OpenCV is not required.
   Use `--monitor-index` if the virtual monitor is not Windows display index 1.
   H.264 is required by default for stable 60 fps. JPEG quality defaults to 40
   only when using the fallback; increase it if image
   quality is more important than responsiveness:

   ```powershell
   python -m duo_host --jpeg-quality 75 --max-fps 60
   ```

   The host normalizes portrait handshake dimensions to landscape, requests
   that mode from the virtual driver, and reports the actual supported mode
   back to the iPad. If the driver cannot provide the requested aspect ratio,
   the iPad uses a full-screen fill presentation, which may crop a small
   amount rather than showing a border.
   During streaming, the host logs measured send FPS separately from the
   monitor's configured refresh rate. A 60 Hz monitor can show less than 60
   streamed frames per second if JPEG encoding or USB transfer is the
   bottleneck.
   The host requires H.264 when the iPad advertises it. Reinstall the runtime
   extra so PyAV is available (`python -m pip install -e ".[runtime]"`). PyAV
   tries `h264_amf`, `h264_nvenc`, and `h264_qsv` before `libx264`, so an AMD,
   NVIDIA, or Intel GPU can encode in hardware and every other Windows PC can
   still stream with software x264. If no encoder opens, the host stops with
   an actionable error instead of silently switching to the slow JPEG path.
   Use `--codec jpeg` only to explicitly select the fallback.
   On Windows, one option for the encoders is:

   ```powershell
   winget install --id Gyan.FFmpeg.Shared
   ```

   Open a new PowerShell window afterward and verify `ffmpeg -encoders`
   lists `libx264` and, when the GPU supports it, `h264_amf`, `h264_nvenc`,
   or `h264_qsv`.
   The startup log includes the iPad HELLO dimensions and advertised codecs.
   It should list `H264`. A HELLO of `2048x1536` means iPadOS is running the
   app in compatibility mode or an older build is installed. The current
   Info.plist includes a launch screen so a rebuilt app reports the panel's
   native pixels (2360x1640 on a 10th-generation iPad). Rebuild and sideload
   after pulling these client changes; the host cannot update the app on the iPad.
   Use `--once` to exit instead of retrying when the iPad is unavailable.

If the host reports a usbmux import error, install the runtime package into
the same interpreter that starts the host:

```powershell
python -m pip install -e ".[runtime]"
python -c "from pymobiledevice3.usbmux import list_devices; import asyncio; print(asyncio.run(list_devices()))"
```

The host supports current `pymobiledevice3` releases and uses the USB device
list returned by usbmuxd. If that list shows the iPad but the host says Duo
refused port `24862`, the cable and trust are already working. The installed
app is not accepting the localhost tunnel. Sideload the current build and
leave it in the foreground.
4. Open the iPad app in the foreground and connect the cable.
5. Sign and install the app with Xcode, SideStore, or AltStore. A free Apple
   ID provisioning profile normally expires after seven days. The host cannot
   update the app on the iPad.

Touch events are sent as normalized coordinates and Windows touch injection is
enabled when the host is run elevated if required by the installed driver.
Apple Pencil events are transported, but pressure-aware Windows pen injection
is still experimental. DRM-protected windows may capture as black, and the
Windows secure desktop, UAC prompts, and lock screen are not capturable. The
iPad client must remain foregrounded while streaming.
