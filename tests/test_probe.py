"""Tests for the model/protocol probe."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anthem_rs232 import probe


class _MockSerial:
    """Mock serial reader/writer pair for the probe."""

    def __init__(self, responses: dict[bytes, bytes] | None = None):
        # ``responses`` maps the bytes the probe writes to the bytes the
        # receiver should "send back". Multiple writes accumulate.
        self.reader = asyncio.StreamReader()
        self.writer = MagicMock()
        self.writer.write = MagicMock()
        self.writer.drain = AsyncMock()
        self.writer.close = MagicMock()
        self.writer.wait_closed = AsyncMock()
        self.written: list[bytes] = []
        self._responses = dict(responses or {})
        self.writer.write.side_effect = self._on_write

    def _on_write(self, data: bytes) -> None:
        self.written.append(data)
        if data in self._responses:
            self.reader.feed_data(self._responses[data])


def _patch_open(serials_by_baud: dict[int, _MockSerial]):
    """Patch serialx.open_serial_connection to return per-baud mock serials."""

    async def fake_open(port, *, baudrate, **kwargs):
        if baudrate not in serials_by_baud:
            # Simulate a port that opens but returns no data at this baud.
            ms = _MockSerial()
            serials_by_baud[baudrate] = ms
        return serials_by_baud[baudrate].reader, serials_by_baud[baudrate].writer

    return patch(
        "anthem_rs232.probe.serialx.open_serial_connection",
        side_effect=fake_open,
    )


# -- Gen 2 detection --------------------------------------------------------


async def test_probe_detects_gen2_idm():
    """A Gen 2 receiver answering IDM? is detected on the first try."""
    serials = {
        115200: _MockSerial({b"IDM?;": b"IDMMRX 1120;"}),
    }
    with _patch_open(serials):
        result = await probe("/dev/ttyUSB0", timeout=0.05)

    assert result is not None
    assert result.generation == 2
    assert result.model_name == "MRX 1120"
    assert result.baud_rate == 115200
    assert result.raw_response == "IDMMRX 1120"
    # Looked up via library model registry.
    from anthem_rs232.models import MRX_1120

    assert result.model is MRX_1120


async def test_probe_detects_gen2_via_z1pow_fallback():
    """Some MRX firmwares drop IDM? in standby; Z1POW? is the fallback."""
    serials = {
        115200: _MockSerial({b"Z1POW?;": b"Z1POW0;"}),
    }
    with _patch_open(serials):
        result = await probe("/dev/ttyUSB0", timeout=0.05)

    assert result is not None
    assert result.generation == 2
    assert result.baud_rate == 115200
    assert "Unknown" in result.model_name
    assert result.model is None


# -- Gen 1 detection --------------------------------------------------------


async def test_probe_detects_gen1_at_9600():
    """A Gen 1 receiver answering ? at 9600 baud."""
    serials = {
        9600: _MockSerial({b"?\n": b"(MRX 700,Version 1.5,Jul 2 2012)\n"}),
    }
    with _patch_open(serials):
        result = await probe("/dev/ttyUSB0", timeout=0.05)

    assert result is not None
    assert result.generation == 1
    assert result.model_name == "MRX 700"
    assert result.baud_rate == 9600
    from anthem_rs232.gen1 import MRX_700

    assert result.model is MRX_700


async def test_probe_detects_gen1_at_19200():
    """Statement D2/D2v ship at 19200; probe reaches them on the third attempt."""
    serials = {
        19200: _MockSerial({b"?\n": b"(Statement D2,Version 3.10,Sep 1 2010)\n"}),
    }
    with _patch_open(serials):
        result = await probe("/dev/ttyUSB0", timeout=0.05)

    assert result is not None
    assert result.generation == 1
    assert result.model_name == "Statement D2"
    assert result.baud_rate == 19200
    from anthem_rs232.gen1 import STATEMENT_D2

    assert result.model is STATEMENT_D2


# -- No-response and ordering ----------------------------------------------


async def test_probe_returns_none_when_silent():
    """Nothing answered at any baud rate."""
    serials: dict = {}
    with _patch_open(serials):
        result = await probe("/dev/ttyUSB0", timeout=0.02)
    assert result is None


async def test_probe_prefers_gen2_over_gen1():
    """Gen 2 is tried first; even if Gen 1 would also respond, Gen 2 wins."""
    serials = {
        115200: _MockSerial({b"IDM?;": b"IDMAVM 60;"}),
        9600: _MockSerial({b"?\n": b"(AVM 50,Version 2.10,Sep 1 2008)\n"}),
    }
    with _patch_open(serials):
        result = await probe("/dev/ttyUSB0", timeout=0.05)
    assert result is not None
    assert result.generation == 2
    assert result.model_name == "AVM 60"


async def test_probe_unknown_model_name_returns_no_constant():
    """Receiver answers but its name doesn't match any library definition."""
    serials = {
        115200: _MockSerial({b"IDM?;": b"IDMMRX 9999;"}),
    }
    with _patch_open(serials):
        result = await probe("/dev/ttyUSB0", timeout=0.05)
    assert result is not None
    assert result.model_name == "MRX 9999"
    assert result.model is None


# -- Custom attempt ordering ------------------------------------------------


async def test_probe_custom_attempts_can_skip_gen2():
    """Custom ``attempts`` lets you skip Gen 2 and only check Gen 1."""
    serials = {
        9600: _MockSerial({b"?\n": b"(AVM 50,Version 2.10,Sep 1 2008)\n"}),
    }
    with _patch_open(serials):
        result = await probe(
            "/dev/ttyUSB0",
            timeout=0.05,
            attempts=((1, 9600),),
        )
    assert result is not None
    assert result.generation == 1
    assert result.baud_rate == 9600
    # Confirm we didn't even open at 115200.
    assert 115200 not in serials


async def test_probe_invalid_generation_raises():
    """Passing a generation other than 1 or 2 raises ValueError."""
    with _patch_open({}):
        with pytest.raises(ValueError):
            await probe("/dev/ttyUSB0", timeout=0.05, attempts=((9, 9600),))


# -- Open failure handling --------------------------------------------------


async def test_probe_handles_open_failure():
    """If a baud-rate attempt's open() raises, the probe keeps trying others."""

    async def fake_open(port, *, baudrate, **kwargs):
        if baudrate == 115200:
            raise OSError("permission denied")
        # 9600 returns a working Gen 1 receiver
        ms = _MockSerial({b"?\n": b"(MRX 500,Version 1.2,Jan 1 2011)\n"})
        return ms.reader, ms.writer

    with patch(
        "anthem_rs232.probe.serialx.open_serial_connection",
        side_effect=fake_open,
    ):
        result = await probe("/dev/ttyUSB0", timeout=0.05)
    assert result is not None
    assert result.generation == 1
    assert result.model_name == "MRX 500"
