"""Runnable Windows host for the Duo JPEG-over-usbmux prototype."""

from __future__ import annotations

import argparse
import logging
import time

from .host import HostController
from .monitor import MonitorError, VirtualMonitor
from .protocol import FrameStream, FrameType, Hello, ProtocolError
from .stream import EncodedFrame, EncoderError, JpegEncoder
from .transport import ReconnectPolicy, TransportError, UsbmuxTransportFactory

LOG = logging.getLogger("duo")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stream a Windows virtual monitor to Duo iPad")
    parser.add_argument("--port", type=int, default=24862)
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--max-fps", type=int, default=60)
    parser.add_argument("--jpeg-quality", type=int, default=40)
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
    controller = HostController(VirtualMonitor(args.driver_name), args.max_fps)
    parser = FrameStream()
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
                    "iPad HELLO: %sx%s @ %s fps (scale %.2f)",
                    hello.width,
                    hello.height,
                    hello.max_fps,
                    hello.scale,
                )
                break
        if hello is None:
            raise TransportError("Timed out waiting for the iPad HELLO message.")

        config = controller.connect(transport, hello)
        LOG.info("Connected: %sx%s at %s fps using %s", config.width, config.height, config.fps, config.codec.name)
        capture = _capture(args.monitor_index, config.fps)
        encoder = JpegEncoder(args.jpeg_quality)
        last_metrics = time.monotonic()
        for image in capture.frames(config.fps):
            encoded = encoder.encode(image)
            controller.send_frame(encoded)
            controller.tick()
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
        return 0
    finally:
        controller.disconnect()
        transport.close()


def _capture(monitor_index: int, fps: int):
    from .monitor import DxcamCapture
    return DxcamCapture(monitor_index)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(build_parser().parse_args())
