from duo_host.protocol import Input


def test_input_round_trip() -> None:
    event = Input(7, 1, 0.25, 0.75, 0.5, True)
    assert Input.decode(event.encode()) == event
