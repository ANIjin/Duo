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
python -m pip install -e ".[dev]"
python -m pytest
```

The iPad client source is under `ipad/`. It is intended to be opened in Xcode
on macOS for signing and device testing.

## Device installation

1. Install the signed IddCx virtual display driver and confirm it appears in
   Windows Display settings.
2. Install Apple Devices or iTunes on Windows so Apple Mobile Device Support
   and usbmux are available. Trust the PC on the iPad.
3. Install the host package with the development extra, then start the host
   controller.
4. Open the iPad app in the foreground and connect the USB-C cable.
5. In Xcode, select the iPad as the run destination and sign the app. A free
   Apple ID provisioning profile normally expires after seven days.

The project is view-only until the Windows touch and pen injection adapters are
enabled. DRM-protected windows may capture as black, and the Windows secure
desktop, UAC prompts, and lock screen are not capturable. The iPad client must
remain foregrounded while streaming; background/foreground resume is still
tracked as a later task.
