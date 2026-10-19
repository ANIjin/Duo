## 1. Phase 0: Feasibility spikes

- [x] 1.1 Record target hardware (Windows GPU and encoder, iPad model, cable) in the project README
- [x] 1.2 Install the open-source virtual display driver; confirm a monitor appears and note whether modes can be set at runtime and whether the install needs test-signing
- [x] 1.3 Confirm Apple Mobile Device Support is present and `pymobiledevice3` can list the iPad over usbmux
- [x] 1.4 Create a minimal iPad app that listens on a TCP port; from the PC, open a usbmux connection to it and exchange a "hello" message
- [x] 1.5 Capture the virtual monitor with `dxcam` and confirm frames arrive at 60 fps
- [x] 1.6 Write findings and any design changes back into `design.md`

## 2. Phase 1: JPEG over USB proof of concept

- [x] 2.1 Define the frame format and implement HELLO, CONFIG, FRAME, PING/PONG, BYE on both sides
- [x] 2.2 Implement host session lifecycle: wait for device, connect, handshake
- [x] 2.3 Create the virtual monitor on connect and remove it on disconnect
- [x] 2.4 Capture the virtual monitor and send JPEG frames with latest-frame-wins dropping
- [x] 2.5 iPad: decode and display JPEG full-screen, disable idle timer, lock landscape
- [x] 2.6 Add heartbeat, 2-second link-loss detection, and auto-reconnect
- [ ] 2.7 Demo: drag a window onto the iPad over USB on an isolated network

## 3. Phase 2: Hardware H.264 and latency

- [x] 3.1 Integrate encoder selection (NVENC, QuickSync, AMF) with software fallback
- [x] 3.2 Configure low-latency encoding: no B-frames, small rate-control buffer, on-demand keyframes
- [x] 3.3 Send parameter sets in CONFIG and implement KEYFRAME_REQ
- [ ] 3.4 iPad: VideoToolbox decode and display-layer rendering
- [x] 3.5 Add timestamps, clock-offset estimation, and p50/p95 latency telemetry
- [x] 3.6 Handle static screens with periodic refresh or heartbeat
- [ ] 3.7 Tune bitrate and frame pacing; record measured latency against the target
- [ ] 3.8 Decision point: if p95 misses target, scope a native capture-encode-send module (design D3)

## 4. Phase 3: Touch and Pencil input

- [ ] 4.1 iPad: capture touch and Pencil events and send normalized coordinates
- [x] 4.2 Host: map coordinates to the virtual monitor bounds
- [ ] 4.3 Host: inject touch via the Windows touch injection API, including multi-touch
- [ ] 4.4 Host: inject pen input with pressure from Apple Pencil
- [x] 4.5 Release all contacts on disconnect; add view-only switch

## 5. Phase 4: Polish and release

- [ ] 5.1 Tray app with start/stop, status, view-only toggle, and settings for bitrate and refresh cap
- [ ] 5.2 Mode negotiation: match the iPad's reported resolution and refresh, with nearest-mode fallback
- [ ] 5.3 Background/foreground handling between iPad and host
- [x] 5.4 Actionable errors for missing driver, missing Apple Mobile Device Support, and version mismatch
- [x] 5.5 Document install steps, sideload and 7-day re-signing, and known limitations (DRM black frames, UAC and lock screen)
- [x] 5.6 Add tests for protocol framing and coordinate mapping; add MIT license and a release build
