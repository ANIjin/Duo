from argparse import Namespace

from duo_host.cli import build_parser


def test_cli_defaults_to_usb_port_and_retrying() -> None:
    args = build_parser().parse_args([])
    assert args.port == 24862
    assert args.once is False


def test_cli_allows_monitor_selection() -> None:
    args = build_parser().parse_args(["--monitor-index", "3", "--once"])
    assert args.monitor_index == 3
    assert args.once is True
