"""Runnable Windows host for the Duo H.264-over-usbmux prototype."""

from __future__ import annotations

import argparse
import logging
import time

from .host import HostController
from .monitor import MonitorError, VirtualMonitor
from .protocol import FrameStream, FrameType, Hello, ProtocolError
from .stream import EncodedFrame, EncoderError, FfmpegEncoder, JpegEncoder
from .transport import ReconnectPolicy, TransportError, UsbmuxTransportFactory

LOG = logging.getLogger("duo")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stream a Windows virtual monitor to Duo iPad")
    parser.add_argument("--port", type=int, default=24862)
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--max-fps", type=int, default=60)
    parser.add_argument("--jpeg-quality", type=int, default=40)
    parser.add_argument(
        "--codec",
        choices=("h264", "jpeg"),
        default="h264",
        help="Codec to use; H.264 is required by default for stable 60 fps.",
    )
    parser.add_argument("--driver-name", default="Virtual Display Driver")
    parser.add_argument("--once", action="store_true", help="Exit after the first disconnect")
    return parser


def run(args: argparse.Namespace) -> int:
    factory = UsbmuxTransportFactory(args.port)
    retry = ReconnectPolicy()
    while True:
        if not retry.ready():
            time.sleep(0.1)
            continue
        try:
            transport = factory.connect()
            retry.succeeded()
            stream_session(transport, args)
            if args.once:
                return 0
            LOG.info("iPad session ended; retrying connection.")
            retry.failed()
        except (TransportError, MonitorError, EncoderError, ProtocolError, OSError) as error:
            LOG.error("%s", error)
            if args.once:
                return 1
            LOG.info("Waiting for iPad; open Duo on the iPad and connect it by USB.")
            retry.failed()


def stream_session(transport, args: argparse.Namespace) -> int:
    controller = HostController(
        VirtualMonitor(args.driver_name),
        args.max_fps,
        codec_preference=args.codec,
    )
    parser = FrameStream()
    capture = None
    try:
        deadline = time.monotonic() + 5
        hello = None
        while hello is None and time.monotonic() < deadline:
            data = transport.recv()
            if not data:
                raise TransportError("The iPad closed the USB connection.")
            for frame in parser.feed(data):
                if frame.message_type != FrameType.HELLO:
                    raise ProtocolError("The first iPad message must be HELLO")
                hello = Hello.decode(frame.payload)
                LOG.info(
                    "iPad HELLO: %sx%s @ %s fps (scale %.2f) codecs %s",
                    hello.width,
                    hello.height,
                    hello.max_fps,
                    hello.scale,
                    ",".join(codec.name for codec in hello.codecs) or "none",
                )
                break
        if hello is None:
            raise TransportError("Timed out waiting for the iPad HELLO message.")

        config = controller.connect(transport, hello)
        LOG.info("Connected: %sx%s at %s fps using %s", config.width, config.height, config.fps, config.codec.name)
        capture = _capture(args.monitor_index, controller.monitor.device_name)
        if config.codec.name == "H264":
            encoder = FfmpegEncoder(config.width, config.height, config.fps)
            LOG.info("Using H.264 encoder %s", encoder.encoder)
            if encoder.warning:
                LOG.warning("%s", encoder.warning)
            try:
                controller.announce_parameter_sets(encoder.parameter_sets)
            except OSError as error:
                LOG.warning("iPad link lost: %s", error)
                return 0
        else:
            encoder = JpegEncoder(args.jpeg_quality)
        last_metrics = time.monotonic()
        try:
            for image in capture.frames(config.fps):
                capture_ns = time.monotonic_ns()
                encoded = encoder.encode(image, keyframe=controller.consume_keyframe_request())
                if encoded is None:
                    controller.tick()
                    if not controller.connected:
                        break
                    continue
                if isinstance(encoder, FfmpegEncoder):
                    controller.announce_parameter_sets(encoder.parameter_sets)
                try:
                    controller.send_frame(encoded, capture_ns)
                except OSError as error:
                    LOG.warning("iPad link lost: %s", error)
                    break
                controller.tick()
                if not controller.connected:
                    break
                if controller.sender is not None and time.monotonic() - last_metrics >= 2:
                    metrics = controller.sender.telemetry.snapshot()
                    LOG.info(
                        "Stream %.1f fps, %.1f Mbps, p50 %.1f ms, p95 %.1f ms, dropped %d",
                        metrics["fps"],
                        metrics["bitrate_bps"] / 1_000_000,
                        metrics["latency_p50_ms"],
                        metrics["latency_p95_ms"],
                        metrics["dropped_frames"],
                    )
                    last_metrics = time.monotonic()
        finally:
            if isinstance(encoder, FfmpegEncoder):
                encoder.close()
        return 0
    finally:
        if capture is not None:
            capture.close()
        controller.disconnect()
        transport.close()


def _capture(monitor_index: int, device_name: str | None):
    from .monitor import DxcamCapture
    return DxcamCapture(monitor_index, device_name)


def main() -> int:
    from .monitor import use_physical_screen_coordinates

    use_physical_screen_coordinates()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(build_parser().parse_args())
