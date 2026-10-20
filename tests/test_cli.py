from argparse import Namespace

from duo_host.cli import build_parser
from duo_host.transport import describe_connect_failure


def test_cli_defaults_to_usb_port_and_retrying() -> None:
    args = build_parser().parse_args([])
    assert args.port == 24862
    assert args.once is False


def test_refused_usb_port_names_the_ipad_listener() -> None:
    message = describe_connect_failure(
        RuntimeError("got an error message: {'MessageType': 'Result', 'Number': 3}"),
        24862,
    )
    assert "refused port 24862" in message
    assert "localhost" in message


def test_other_usbmux_errors_still_mention_apple_devices() -> None:
    message = describe_connect_failure(OSError("timed out"), 24862)
    assert "Apple Devices" in message


def test_cli_allows_monitor_selection() -> None:
    args = build_parser().parse_args(["--monitor-index", "3", "--once"])
    assert args.monitor_index == 3
    assert args.once is True
