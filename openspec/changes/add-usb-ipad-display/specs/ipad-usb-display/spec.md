## ADDED Requirements

### Requirement: Connection over USB without an IP network
The host SHALL communicate with the iPad client over a USB cable using Apple's usbmux service, and SHALL NOT require the PC and iPad to share any network.

#### Scenario: Isolated network
- **WHEN** the PC is on a network that blocks client-to-client traffic and the iPad is on a different or no network
- **THEN** the host and iPad still connect and stream over the USB cable

### Requirement: Device discovery and auto-connect
The host SHALL detect when a trusted iPad is attached or detached and SHALL connect automatically when the iPad client is listening.

#### Scenario: Plug in with client running
- **WHEN** the iPad client is running in the foreground and the iPad is connected by USB
- **THEN** the host connects within 3 seconds without user action

#### Scenario: Client not running
- **WHEN** an iPad is attached but nothing is listening on the client port
- **THEN** the host keeps retrying at a bounded interval
- **AND** shows "Open the app on your iPad" as the status

### Requirement: Missing USB service reported
The host SHALL detect when the usbmux service is unavailable and report how to fix it.

#### Scenario: Apple Mobile Device Support not installed
- **WHEN** the host cannot reach the usbmux service
- **THEN** it displays that Apple Mobile Device Support is required and how to install it

### Requirement: Versioned framed protocol
All messages SHALL use a length-prefixed binary frame with a type field, and both sides SHALL exchange protocol versions in the first message.

#### Scenario: Version mismatch
- **WHEN** the host and iPad client report incompatible protocol versions
- **THEN** both sides show a message naming both versions and which side to update
- **AND** no video or input data is exchanged

### Requirement: Link loss detection and recovery
Each side SHALL detect a dead link within 2 seconds using heartbeats and the host SHALL reconnect automatically.

#### Scenario: Cable unplugged and replugged
- **WHEN** the USB cable is disconnected during a session
- **THEN** both sides report disconnected within 2 seconds
- **AND** after the cable is reconnected, the session resumes without restarting either app

### Requirement: Dedicated virtual monitor per session
The host SHALL present a virtual monitor to Windows for the duration of a connected session, so windows can be dragged onto the iPad like any other display.

#### Scenario: Monitor appears on connect
- **WHEN** an iPad client connects and completes the handshake
- **THEN** a new monitor appears in Windows display settings
- **AND** it is extended (not mirrored) by default

#### Scenario: Monitor removed on disconnect
- **WHEN** the iPad disconnects or the host app exits
- **THEN** the virtual monitor is removed
- **AND** windows that were on it move to a remaining display

### Requirement: Mode matches the iPad
The virtual monitor SHALL use a resolution and refresh rate derived from the capabilities the iPad reports in its handshake, capped by configurable limits.

#### Scenario: Native resolution
- **WHEN** the iPad reports its pixel dimensions and maximum refresh rate
- **THEN** the virtual monitor is set to those dimensions
- **AND** the refresh rate is the lower of the iPad's maximum and the configured cap

#### Scenario: Unsupported mode
- **WHEN** the driver cannot provide the requested mode
- **THEN** the host selects the nearest supported mode with the same aspect ratio
- **AND** informs the iPad of the resulting mode in its configuration message

### Requirement: Driver dependency detection
The host SHALL detect whether the virtual display driver is installed before starting a session.

#### Scenario: Driver missing
- **WHEN** the user starts a session and the driver is not installed
- **THEN** the host does not start streaming
- **AND** shows an actionable message explaining how to install the driver

### Requirement: Capture only the virtual monitor
The host SHALL capture frames from the virtual monitor only, not from the primary or other displays.

#### Scenario: Window on primary display
- **WHEN** a window is on the laptop's main display and not on the virtual monitor
- **THEN** its contents do not appear on the iPad

### Requirement: Phase 1 JPEG streaming
The host SHALL support streaming frames as individually compressed JPEG images as a baseline codec.

#### Scenario: Proof-of-concept stream
- **WHEN** the codec is set to JPEG
- **THEN** the iPad displays the virtual monitor at a usable frame rate
- **AND** no hardware video encoder is required

### Requirement: Low-latency hardware H.264
The host SHALL support H.264 encoding using a hardware encoder when available, configured for low latency: no B-frames, a small rate-control buffer, and keyframes sent on request rather than at a fixed interval.

#### Scenario: Hardware encoder available
- **WHEN** a supported hardware encoder is detected
- **THEN** the host uses it and reports which encoder is active

#### Scenario: No hardware encoder
- **WHEN** no supported hardware encoder is detected
- **THEN** the host falls back to a software encoder with a zero-latency preset
- **AND** warns that latency may be higher

### Requirement: Latest frame wins
The host SHALL NOT build an unbounded queue of frames. When the link or the iPad decoder cannot keep up, the host SHALL drop stale frames and keep the newest.

#### Scenario: Slow link
- **WHEN** the send queue exceeds a small fixed bound
- **THEN** the oldest queued frames are dropped
- **AND** a keyframe is sent next if dropped frames were needed as references

### Requirement: Keyframe on demand
The host SHALL send a keyframe when a session starts, when the iPad requests one, and after any dropped reference frame.

#### Scenario: Client requests keyframe
- **WHEN** the iPad sends a keyframe request
- **THEN** the next encoded frame is a keyframe

### Requirement: Unchanged screens stay alive
The host SHALL keep the stream alive when the screen is not changing so the iPad does not appear frozen or disconnected.

#### Scenario: Static desktop
- **WHEN** no pixels change for several seconds
- **THEN** the host sends a periodic refresh or heartbeat
- **AND** the iPad continues to show the current image without a disconnect

### Requirement: Latency telemetry
The host SHALL expose an estimate of capture-to-present latency, derived from frame timestamps and a clock-offset estimate from ping exchanges.

#### Scenario: Reading latency
- **WHEN** a session is streaming
- **THEN** the host can display or log p50 and p95 latency, frames per second, bitrate, and dropped-frame count

### Requirement: Full-screen display
The iPad client SHALL render the received video full-screen in landscape with no on-screen controls while streaming.

#### Scenario: Streaming
- **WHEN** video frames are arriving
- **THEN** the video fills the screen without interface chrome
- **AND** the screen does not auto-dim or lock

### Requirement: Hardware decoding
The iPad client SHALL decode H.264 using the system's hardware decoder and present frames as soon as they are decoded.

#### Scenario: Decode and present
- **WHEN** an H.264 frame arrives
- **THEN** it is decoded and shown without waiting for later frames

### Requirement: JPEG decoding
The iPad client SHALL decode and display JPEG frames for the baseline codec.

#### Scenario: JPEG stream
- **WHEN** the host selects JPEG in its configuration message
- **THEN** the client displays each received image as it arrives

### Requirement: Waiting and error states
When no host is connected, the client SHALL show a simple status screen that says it is waiting for a PC and shows the protocol version and any connection error.

#### Scenario: App open, no PC
- **WHEN** the app is open and no host has connected
- **THEN** it shows "Waiting for PC" and the cable-connection hint

#### Scenario: Protocol mismatch
- **WHEN** the host reports an incompatible version
- **THEN** the client shows both versions and which side needs updating

### Requirement: Foreground and background handling
The client SHALL tell the host when it moves to the background and SHALL resume streaming when it returns to the foreground.

#### Scenario: User switches apps
- **WHEN** the iPad app is backgrounded
- **THEN** the host pauses encoding and holds the virtual monitor
- **AND** on return, a keyframe is requested and streaming resumes without reconnecting by hand

### Requirement: Touch injected as Windows touch
Touch events on the iPad SHALL be sent to the host and injected into Windows as touch input on the virtual monitor.

#### Scenario: Tap
- **WHEN** the user taps a point on the iPad
- **THEN** Windows receives a touch tap at the corresponding point on the virtual monitor

#### Scenario: Multi-touch
- **WHEN** the user performs a two-finger gesture
- **THEN** both contact points are injected so Windows can recognize pinch or scroll gestures

### Requirement: Apple Pencil as pen input
Apple Pencil events SHALL be sent to the host and injected as pen input with position and pressure.

#### Scenario: Drawing with pressure
- **WHEN** the user draws with varying pressure
- **THEN** Windows pen-aware apps receive the corresponding pressure values

### Requirement: Normalized coordinates confined to the virtual monitor
The iPad SHALL send coordinates normalized to the video area, and the host SHALL map them to the virtual monitor's bounds so that input never lands on another display.

#### Scenario: Different resolutions
- **WHEN** the iPad's point resolution differs from the virtual monitor's pixel resolution
- **THEN** a touch at 50% across the iPad lands at 50% across the virtual monitor

### Requirement: View-only mode
The host SHALL provide a switch to ignore all input from the iPad.

#### Scenario: View-only enabled
- **WHEN** view-only is on
- **THEN** touches and Pencil events from the iPad have no effect on Windows

### Requirement: No stuck input
The host SHALL release all active touch and pen contacts when the link drops or the session ends.

#### Scenario: Cable pulled mid-drag
- **WHEN** the connection is lost while a finger is down
- **THEN** the host injects contact-up events for all active contacts
