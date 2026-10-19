## Why

On a university network with client isolation, network-based second-display tools (Spacedesk, Sunshine/Moonlight, Duet wireless) cannot reach the iPad. Duet's wired mode works because it tunnels over the USB cable, but it is closed source and subscription-based. There is no free, open-source way to use an iPad as a low-latency wired second monitor for a Windows PC, and building one is a good end-to-end systems project (graphics drivers, video encoding, USB tunneling, iOS decoding, input injection).

## What Changes

- Add a Windows host app that creates a virtual monitor, captures it, encodes it, and streams it to an iPad over USB.
- Add an iPad client app that receives the stream, decodes it with hardware, and displays it full-screen.
- Add a USB link layer that tunnels a framed protocol through Apple's usbmux service, so no IP network is needed.
- Add touch and Apple Pencil input from the iPad, injected into Windows as touch and pen input on the virtual monitor.
- Deliver in phases: JPEG-over-USB proof of concept first, then hardware H.264 with latency instrumentation, then input, then polish.

## Capabilities

### New Capabilities

- `ipad-usb-display`: virtual monitor, USB link, video streaming, iPad client, and touch/Pencil input for using an iPad as a wired second display for Windows

### Modified Capabilities

None. This is a greenfield project.

## Impact

- **Platforms:** Windows 10/11 host, iPadOS client. macOS and Android hosts are out of scope.
- **Dependencies:** an open-source indirect display driver (virtual monitor), Apple Mobile Device Support on the PC (provides usbmux, installed with iTunes or the Apple Devices app), FFmpeg or a native hardware encoder, Xcode for building the iPad app.
- **Distribution:** the iPad app is sideloaded via Xcode. A free Apple ID provisioning profile expires after 7 days and needs re-signing; a paid developer account avoids that.
- **Out of scope for this change:** audio, wireless mode, multiple iPads, HDR, clipboard sync, DRM-protected content, and macOS host support.

## Assumptions

- The host PC has a GPU with a hardware H.264 encoder (NVENC, QuickSync, or AMF). A software fallback is specified but is expected to cost latency.
- The user is comfortable installing a third-party virtual display driver.
- Target hardware details (exact GPU and iPad model) are not yet known and are recorded as open questions in `design.md`.
