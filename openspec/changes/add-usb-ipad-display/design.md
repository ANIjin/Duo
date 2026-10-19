## Context

Greenfield project; there is no existing codebase to inspect. The design is grounded in how comparable products (Duet, Sunshine/Moonlight, Spacedesk) are generally understood to work, not in observed behavior of this project. Anything marked "to verify" is an assumption the Phase 0 spikes must confirm.

Pipeline:

```
Windows host                                              iPad
-----------------------------------------------           -------------------------
virtual monitor -> capture -> encode -> usbmux  ==USB==>  listener -> decode -> render
                                                  <==USB==  touch/Pencil events
inject touch/pen <- map to monitor coords <-------
```

## Goals / Non-Goals

**Goals**
- Wired USB only; works on networks that isolate clients.
- Capture-to-present latency target of p50 <= 50 ms and p95 <= 80 ms at 60 fps on target hardware (a goal to be measured in Phase 2, not a guarantee).
- iPad usable as a touch and Pencil display in Windows.
- Fully open source, with each stage understandable on its own (educational value).

**Non-Goals**
- Audio, wireless mode, multi-device, HDR, DRM content, macOS/Android hosts, App Store distribution.

## Decisions

### D1. Virtual monitor: reuse an existing open-source indirect display driver
Do not write a driver. Use the open-source Virtual Display Driver project (IddCx-based). The host app drives it for add/remove and mode changes. *To verify in Phase 0:* how to set a custom resolution and refresh programmatically, and whether the release is signed for normal (non-test-signing) installs.

### D2. USB transport: usbmux, PC connects to a port the iPad listens on
The iPad app listens on a TCP port; the PC connects through the usbmux service using the device ID. This is the direction usbmux supports. The host uses `pymobiledevice3` (Python) for usbmux access. Alternatives considered: raw libusb (rejected: needs MFi-style access and driver work), network over USB tethering (rejected: not available on iPad without extra setup and reintroduces IP dependency).

### D3. Host language: Python for Phases 1-3, native hot path only if measured need
Python 3.11+ with `dxcam` (Desktop Duplication capture), PyAV/FFmpeg (encode), `pymobiledevice3` (usbmux), and `ctypes` for touch injection. Heavy work (capture, encode) runs in native code, so Python mainly orchestrates. Risk: GC and GIL jitter. Mitigation: keep the frame path allocation-light, use a dedicated capture/encode thread, and measure. If p95 misses target after tuning, move the capture-encode-send loop to a native module (C++ or Rust). The decision is revisited at the end of Phase 2.

### D4. Video codec: JPEG first, then H.264 with low-latency settings
- Phase 1: JPEG per frame, to prove the whole path end-to-end with minimal moving parts.
- Phase 2: H.264 via hardware encoder (`h264_nvenc`, `h264_qsv`, or `h264_amf`), Annex B or AVCC with parameter sets sent in CONFIG, no B-frames, small rate-control buffer, on-demand IDR frames instead of periodic large keyframes. Software fallback: x264 ultrafast + zerolatency.
- HEVC is deferred; H.264 has the broadest hardware support on both ends.

### D5. Backpressure: latest frame wins
Never queue frames. If the send queue or the iPad decoder is behind, drop older frames and request a keyframe if reference frames were dropped. Low latency beats completeness for a live display.

### D6. Wire protocol: length-prefixed binary frames
Each message: `u32 length | u8 type | u8 flags | payload`. Types: `HELLO` (protocol version, device model, screen size in pixels, scale, max fps, supported codecs), `CONFIG` (codec, resolution, fps, parameter sets), `FRAME` (host timestamp, keyframe flag, bytes), `INPUT` (touch/pen events), `PING`/`PONG` (RTT and clock offset estimate), `KEYFRAME_REQ`, `BYE`. Version mismatch yields a clear error on both sides rather than garbage.

### D7. iPad client: Swift, Network.framework, VideoToolbox, display-layer rendering
`NWListener` for the TCP port, `VTDecompressionSession` for decode, and `AVSampleBufferDisplayLayer` with display-immediately flags for presentation. Idle timer disabled while streaming. Landscape only.

### D8. Input: normalized coordinates, injected as Windows touch and pen
The iPad sends coordinates normalized to 0..1 within the video area. The host maps them to the virtual monitor's rectangle and injects through the Windows touch injection and synthetic pen pointer APIs. Pressure from Apple Pencil maps to pen pressure.

### D9. Latency measurement
Frames carry a host monotonic timestamp. PING/PONG exchanges estimate clock offset and RTT. The iPad reports decode-complete and present times back in telemetry; the host shows p50/p95 of the estimated capture-to-present latency in a debug overlay or log.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Virtual display driver signing or install friction | Phase 0 spike; document install steps; fall back to test-signing mode only if unavoidable |
| Apple Mobile Device Support missing on PC | Detect on startup and show an actionable message (install iTunes or the Apple Devices app) |
| Python jitter breaks latency target | Measure in Phase 2; native hot-path module as planned fallback (D3) |
| iPad app only streams while foregrounded | Pause stream on background, resume on return; document as a limitation |
| Sideloaded app expires every 7 days on a free Apple ID | Document re-signing; paid developer account as option |
| USB 2.0 bandwidth if a cable or port is slow | Configurable bitrate with conservative default (start around 20 Mbps, tune up) |
| DRM or protected windows render black on capture | Documented limitation, no workaround |
| Capture cannot see UAC secure desktop or lock screen | Documented limitation |

## Migration Plan

Not applicable (new project). Rollout is phased per `tasks.md`; each phase ends with a demonstrable milestone and a decision point.

## Open Questions

- Host feasibility check (2026-10-19): Windows 11 Home build 10.0.26200 with
  an AMD Radeon 880M Graphics adapter and driver 32.0.22076.3001. AMF is the
  expected hardware encoder; availability still needs confirmation with an
  encoder probe.
- iPad model is currently recorded as an iPad 10th generation with USB-C,
  supplied by the user; the exact model identifier and native resolution still
  need confirmation on-device.
- Can the virtual display driver set arbitrary modes at runtime, or only from a preconfigured list?
- Project name and license (MIT assumed).

## Phase 0 findings

The user manually verified the virtual display driver, Apple Mobile Device
Support/usbmux discovery, the TCP hello exchange, and 60 fps virtual-monitor
capture. Exact driver mode and signing observations should be retained with the
local hardware notes. The repository contains Python protocol, coordinate,
capture, and transport code plus an iPad client transport and JPEG renderer.
