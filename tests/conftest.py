"""Shared test fixtures for anthem_rs232."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import anthem_rs232
import anthem_rs232.receiver as anthem_receiver
from anthem_rs232 import AnthemReceiver
from anthem_rs232.models import ReceiverModel

# Speed up tests by reducing delays.
anthem_rs232.COMMAND_TIMEOUT = 0.1
anthem_rs232.PROBE_TIMEOUT = 0.01
anthem_receiver.COMMAND_TIMEOUT = 0.1
anthem_receiver.PROBE_TIMEOUT = 0.01

# Default responses for query prefixes used during connect()/query_state().
# Each entry maps the queried prefix to a list of full response messages
# (without the trailing ``;``). Multiple messages are emitted in order.
DEFAULT_QUERY_RESPONSES: dict[str, list[str]] = {
    "IDM": ["IDMMRX 1120"],
    "IDS": ["IDS0.2.3"],
    "IDR": ["IDRUS"],
    "IDB": ["IDBOct 23 2015"],
    "IDH": ["IDH1"],
    "IDN": ["IDN7CB77B014FE5"],
    "ECH": ["ECH1"],
    "FPB": ["FPB2"],
    "SIP": ["SIP1"],
    "ICN": ["ICN3"],
    "ISN01": ["ISN01CBL"],
    "ISN02": ["ISN02BD"],
    "ISN03": ["ISN03GAME"],
    "ILN01": ["ILN01Cable Box"],
    "ILN02": ["ILN02Blu-ray Player"],
    "ILN03": ["ILN03Game Console"],
    "Z1POW": ["Z1POW1"],
    "Z1INP": ["Z1INP01"],
    "Z1VOL": ["Z1VOL-35"],
    "Z1MUT": ["Z1MUT0"],
    "Z1ARC": ["Z1ARC1"],
    "Z1BAL": ["Z1BAL050"],
    "Z1ALM": ["Z1ALM00"],
    "Z1DYN": ["Z1DYN0"],
    "Z1DIA": ["Z1DIA0"],
    "Z1AIC": ["Z1AIC6"],
    "Z1AIF": ["Z1AIF3"],
    "Z1AIN": ["Z1AINDTS Master Audio"],
    "Z1AIR": ["Z1AIR48 kHz"],
    "Z1BRT": ["Z1BRT0"],
    "Z1SRT": ["Z1SRT48"],
    "Z1VIR": ["Z1VIR2"],
    "Z1IRH": ["Z1IRH1920"],
    "Z1IRV": ["Z1IRV1080"],
    "Z1TBS": ["Z1TBS0"],
    "T1FMS": ["T1FMS100.10"],
    "T1PSA": ["T1PSA00"],
    "Z2POW": ["Z2POW0"],
    "Z2INP": ["Z2INP01"],
    "Z2VOL": ["Z2VOL-50"],
    "Z2MUT": ["Z2MUT0"],
    "Z2TBS": ["Z2TBS0"],
}


class MockSerialConnection:
    """Mock the serial reader/writer pair with auto-response support.

    Anthem terminates messages with ``;`` (semicolon).
    """

    def __init__(self):
        self.reader = asyncio.StreamReader()
        self.writer = MagicMock()
        self.writer.write = MagicMock()
        self.writer.drain = AsyncMock()
        self.writer.close = MagicMock()
        self.writer.wait_closed = AsyncMock()
        self.written_data: list[bytes] = []
        self._query_responses: dict[str, list[str]] = {}
        self._command_handler: Callable[[str], None] | None = None
        self.writer.write.side_effect = self._on_write

    def _on_write(self, data: bytes) -> None:
        """Track written data and auto-respond to queries."""
        self.written_data.append(data)
        cmd = data.decode("ascii").rstrip(";")
        if cmd.endswith("?"):
            prefix = cmd[:-1]
            for resp in self._query_responses.get(prefix, []):
                self.inject_response(resp)
        elif self._command_handler is not None:
            self._command_handler(cmd)

    def inject_response(self, message: str) -> None:
        """Simulate the receiver sending a message (without the ``;``)."""
        self.reader.feed_data(f"{message};".encode("ascii"))


@pytest.fixture
async def mock_serial():
    return MockSerialConnection()


@pytest.fixture
async def receiver(mock_serial):
    """Create a connected AnthemReceiver with mocked serial."""
    recv = AnthemReceiver("/dev/ttyUSB0")
    mock_serial._query_responses = dict(DEFAULT_QUERY_RESPONSES)

    async def fake_open(*args, **kwargs):
        return mock_serial.reader, mock_serial.writer

    with patch(
        "anthem_rs232.receiver.serialx.open_serial_connection",
        side_effect=fake_open,
    ):
        await recv.connect()
        await recv.query_state()

    # Clear auto-responses so tests can inject specific responses manually.
    mock_serial._query_responses.clear()

    yield recv

    if recv.connected:
        await recv.disconnect()


async def connect_with_defaults(
    mock: MockSerialConnection, model: ReceiverModel | None = None
) -> AnthemReceiver:
    """Helper: connect a receiver with default auto-responses."""
    mock._query_responses = dict(DEFAULT_QUERY_RESPONSES)
    recv = AnthemReceiver("/dev/ttyUSB0", model=model)

    async def fake_open(*args, **kwargs):
        return mock.reader, mock.writer

    with patch(
        "anthem_rs232.receiver.serialx.open_serial_connection",
        side_effect=fake_open,
    ):
        await recv.connect()
        await recv.query_state()

    return recv
