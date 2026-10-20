"""USB transport adapters and bounded reconnect policy."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import socket
import time
from typing import Callable, Protocol


class TransportError(RuntimeError):
    """Raised when Apple Mobile Device Support/usbmux cannot be used."""


class ByteTransport(Protocol):
    def send(self, data: bytes) -> None: ...
    def recv(self, size: int = 65536) -> bytes: ...
    def close(self) -> None: ...


class SocketTransport:
    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection

    def send(self, data: bytes) -> None:
        self.connection.sendall(data)

    def recv(self, size: int = 65536) -> bytes:
        return self.connection.recv(size)

    def close(self) -> None:
        try:
            self.connection.close()
        except OSError:
            return


class UsbmuxTransportFactory:
    """Connect to the iPad TCP listener through pymobiledevice3 usbmux."""

    def __init__(self, port: int) -> None:
        self.port = port

    def connect(self) -> ByteTransport:
        try:
            from pymobiledevice3.usbmux import list_devices
        except ImportError as error:
            raise TransportError(
                "pymobiledevice3 is not available to this Python interpreter. "
                "Install it with 'python -m pip install pymobiledevice3'."
            ) from error
        try:
            device = asyncio.run(self._find_device(list_devices))
            if device is None:
                raise TransportError(
                    "No trusted iPad is attached over USB. Unlock the iPad, tap Trust, "
                    "and keep Duo open in the foreground."
                )
            connection = asyncio.run(device.connect(self.port))
            connection.setblocking(True)
            return SocketTransport(connection)
        except TransportError:
            raise
        except Exception as error:
            raise TransportError(
                f"usbmux connection failed: {error}. Confirm Apple Devices/iTunes "
                "is installed, the iPad is trusted, and Duo is listening."
            ) from error

    @staticmethod
    async def _find_device(list_devices):
        devices = await list_devices()
        usb_devices = [device for device in devices if device.is_usb]
        return usb_devices[0] if usb_devices else None


@dataclass(slots=True)
class ReconnectPolicy:
    retry_interval: float = 1.0
    max_interval: float = 5.0
    _next_attempt: float = 0.0
    _current_interval: float = 1.0

    def ready(self, now: float | None = None) -> bool:
        return (time.monotonic() if now is None else now) >= self._next_attempt

    def failed(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        self._next_attempt = current + self._current_interval
        self._current_interval = min(self.max_interval, self._current_interval * 2)

    def succeeded(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        self._current_interval = self.retry_interval
        self._next_attempt = current


def reconnect_loop(
    connect: Callable[[], ByteTransport],
    on_connected: Callable[[ByteTransport], None],
    stop: Callable[[], bool],
    policy: ReconnectPolicy | None = None,
) -> None:
    """Retry without busy looping until the caller asks the loop to stop."""

    retry = policy or ReconnectPolicy()
    while not stop():
        if not retry.ready():
            time.sleep(0.05)
            continue
        try:
            transport = connect()
        except TransportError:
            retry.failed()
            continue
        retry.succeeded()
        on_connected(transport)
