# Duo

Duo is an experimental wired USB second-display project for Windows and iPadOS.

## Feasibility target

- Host: Windows 11 Home, build 10.0.26200
- GPU: AMD Radeon 880M Graphics, driver 32.0.22076.3001
- Expected hardware encoder: AMD AMF (to verify with the host encoder probe)
- iPad: iPad 10th generation (user supplied; exact display mode to verify)
- Cable: USB-C
- Target mode: TBD; the client will advertise its native pixel dimensions

The following Phase 0 checks still require the target devices and installed Apple
Mobile Device Support were manually completed by the project owner, including
virtual display-driver installation, usbmux discovery, the hello exchange, and
60 fps capture. Exact local driver observations are hardware-specific.

The current host code intentionally keeps the driver, capture, usbmux, and
encoder integrations behind explicit adapters. This allows protocol tests to
run in GitHub Actions without pretending CI has an attached iPad.

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

1. Install the signed IddCx virtual display driver and confirm it appears in
   Windows Display settings.
2. Install Apple Devices or iTunes on Windows so Apple Mobile Device Support
   and usbmux are available. Trust the PC on the iPad.
3. Install the host package with the runtime extra, then start the host:

   ```powershell
   python -m duo_host
   ```

   The default driver name is `Virtual Display Driver` (MikeTheTech's driver).
   Use `--driver-name` if a different IddCx driver is installed.
   Use `--monitor-index` if the virtual monitor is not Windows display index 1.
   JPEG quality defaults to 40 to reduce USB latency; increase it if image
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
   The startup log includes the iPad HELLO dimensions. With the current iPad
   build it should say `2360x1640`; if it says `2048x1536`, rebuild and
   sideload the latest IPA because that is an older client build.
   Use `--once` to exit instead of retrying when the iPad is unavailable.

If the host reports a usbmux import error, install the runtime package into
the same interpreter that starts the host:

```powershell
python -m pip install -e ".[runtime]"
python -c "from pymobiledevice3.usbmux import list_devices; import asyncio; print(asyncio.run(list_devices()))"
```

The host supports current `pymobiledevice3` releases and uses the USB device
list returned by usbmuxd. If the iPad appears in that command but the app does
not connect, keep Duo in the foreground and verify that port `24862` is the
port configured in the iPad app.
4. Open the iPad app in the foreground and connect the USB-C cable.
5. In Xcode, select the iPad as the run destination and sign the app. A free
   Apple ID provisioning profile normally expires after seven days.

Touch events are sent as normalized coordinates and Windows touch injection is
enabled when the host is run elevated if required by the installed driver.
Apple Pencil events are transported, but pressure-aware Windows pen injection
is still experimental. DRM-protected windows may capture as black, and the
Windows secure desktop, UAC prompts, and lock screen are not capturable. The
iPad client must remain foregrounded while streaming.
