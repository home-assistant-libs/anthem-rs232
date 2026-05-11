"""Tests for the Anthem Gen 1 protocol (gen1 subpackage)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import anthem_rs232.gen1.receiver as gen1_receiver_mod
from anthem_rs232.gen1 import (
    AVM_50,
    MRX_700,
    STATEMENT_D2,
    DecoderMode,
    DolbyDynamicRange,
    EffectMode,
    Gen1CommandError,
    Gen1Receiver,
    Gen1ReceiverState,
    SleepTimer,
    Source,
    TunerBand,
    _db_to_param,
    _parse_db,
)
from anthem_rs232.gen1.protocol import (
    parse_am_frequency,
    parse_decoder,
    parse_effect,
    parse_fm_frequency,
    parse_headphone_status,
    parse_main_status,
    parse_mute,
    parse_power,
    parse_rec_source,
    parse_source,
    parse_trigger,
    parse_version,
    parse_volume,
    parse_zone2_status,
    split_lines,
)

# Speed up tests.
gen1_receiver_mod.COMMAND_TIMEOUT = 0.1


# -- dB helpers --------------------------------------------------------------


def test_parse_db_negative():
    assert _parse_db("-30.5") == -30.5


def test_parse_db_positive():
    assert _parse_db("+5.0") == 5.0


def test_parse_db_zero():
    assert _parse_db("0") == 0.0


def test_parse_db_invalid():
    with pytest.raises(ValueError):
        _parse_db("abc")


def test_db_to_param_one_decimal():
    assert _db_to_param(-30.5) == "-30.5"
    assert _db_to_param(0.0) == "0.0"
    assert _db_to_param(5.0) == "5.0"


def test_db_to_param_snaps_to_main_step():
    # 0.5 dB step (Main).
    assert _db_to_param(-30.4, step=0.5) == "-30.5"
    assert _db_to_param(-30.2, step=0.5) == "-30.0"


def test_db_to_param_snaps_to_zone2_step():
    # 1.25 dB step (Zone 2 / Headphone).
    assert _db_to_param(-30.0, step=1.25) == "-30.0"
    assert _db_to_param(-29.5, step=1.25) == "-30.0"  # snaps to 1.25 grid


# -- Compound zone status ----------------------------------------------------


def test_parse_main_status_full():
    s = parse_main_status("P1S5V-30.5M0D0E0")
    assert s is not None
    assert s.source == "5"
    assert s.volume == -30.5
    assert s.mute is False
    assert s.decoder == 0
    assert s.effect == 0


def test_parse_main_status_minimal():
    # Some firmwares omit D and E.
    s = parse_main_status("P1S5V-30.5M0")
    assert s is not None
    assert s.source == "5"
    assert s.decoder is None
    assert s.effect is None


def test_parse_main_status_letter_source():
    s = parse_main_status("P1SdV-15.0M1D1E2")
    assert s is not None
    assert s.source == "d"
    assert s.mute is True


def test_parse_zone2_status():
    s = parse_zone2_status("P2S4V-50.0M1")
    assert s is not None
    assert s.source == "4"
    assert s.volume == -50.0
    assert s.mute is True


def test_parse_rec_source():
    assert parse_rec_source("P3S5") == "5"


def test_parse_headphone_status():
    s = parse_headphone_status("HS1V-15.0M0")
    assert s is not None
    assert s.source == "1"
    assert s.volume == -15.0
    assert s.mute is False


# -- Single-field parsers ----------------------------------------------------


def test_parse_power():
    f = parse_power("P1P1")
    assert f.zone == 1 and f.value is True


def test_parse_volume():
    f = parse_volume("P1V-25.5")
    assert f.zone == 1 and f.value == -25.5


def test_parse_volume_with_VM_prefix():
    # The receiver returns ``P1VMsxx.x`` for the volume query.
    f = parse_volume("P1VM-30.5")
    assert f.zone == 1 and f.value == -30.5


def test_parse_mute():
    f = parse_mute("P2M1")
    assert f.zone == 2 and f.value is True


def test_parse_source():
    f = parse_source("P1S5")
    assert f.zone == 1 and f.value == "5"


def test_parse_decoder():
    assert parse_decoder("P1D5 3") is None  # spec uses "P1Dyx" with no space
    assert parse_decoder("P1D53") == (5, 3)


def test_parse_effect():
    assert parse_effect("P1E51") == (5, 1)


def test_parse_fm_frequency():
    assert parse_fm_frequency("TFT101.5") == 101.5


def test_parse_am_frequency():
    assert parse_am_frequency("TAT0540") == 540


def test_parse_trigger():
    assert parse_trigger("t1T1") == (1, True)
    assert parse_trigger("t2T0") == (2, False)


def test_parse_version():
    info = parse_version("(AVM 2,Version 1.00,Jun 26 2000)")
    assert info == "AVM 2,Version 1.00,Jun 26 2000"


# -- Frame splitting ---------------------------------------------------------


def test_split_lines_lf_only():
    msgs, residual = split_lines(b"P1P1\nP1S5\n")
    assert msgs == [b"P1P1", b"P1S5"]
    assert residual == b""


def test_split_lines_partial_last():
    msgs, residual = split_lines(b"P1P1\nP1V")
    assert msgs == [b"P1P1"]
    assert residual == b"P1V"


def test_split_lines_chained_commands():
    # `;` separates multiple commands within a single LF-terminated line.
    msgs, residual = split_lines(b"P1P1;P1S5;P1VMU\n")
    assert msgs == [b"P1P1", b"P1S5", b"P1VMU"]
    assert residual == b""


# -- Mock serial fixture -----------------------------------------------------


class MockGen1Serial:
    """Mock serial reader/writer pair for Gen 1."""

    def __init__(self):
        self.reader = asyncio.StreamReader()
        self.writer = MagicMock()
        self.writer.write = MagicMock()
        self.writer.drain = AsyncMock()
        self.writer.close = MagicMock()
        self.writer.wait_closed = AsyncMock()
        self.written: list[bytes] = []
        self._handlers: dict[bytes, list[bytes]] = {}
        self.writer.write.side_effect = self._on_write

    def _on_write(self, data: bytes) -> None:
        self.written.append(data)
        cmd = data.rstrip(b"\n")
        for piece in cmd.split(b";"):
            piece = piece.strip()
            if piece in self._handlers:
                for resp in self._handlers[piece]:
                    self.feed(resp)

    def feed(self, message: bytes) -> None:
        self.reader.feed_data(message + b"\n")

    def respond_to(self, command: bytes, *responses: bytes) -> None:
        self._handlers[command] = list(responses)


@pytest.fixture
async def mock_serial_gen1():
    return MockGen1Serial()


@pytest.fixture
async def gen1(mock_serial_gen1):
    """A connected Gen1Receiver hooked up to the mock serial."""
    # Default: respond to identify and SST1 (the connect probes).
    mock_serial_gen1.respond_to(b"?", b"(Statement D2,Version 3.10,Sep 1 2010)")

    recv = Gen1Receiver("/dev/ttyUSB0", model=STATEMENT_D2)

    async def fake_open(*args, **kwargs):
        return mock_serial_gen1.reader, mock_serial_gen1.writer

    with patch(
        "anthem_rs232.gen1.receiver.serialx.open_serial_connection",
        side_effect=fake_open,
    ):
        await recv.connect()

    yield recv

    if recv.connected:
        await recv.disconnect()


# -- Receiver lifecycle ------------------------------------------------------


async def test_connect_uses_model_baud(mock_serial_gen1):
    recv = Gen1Receiver("/dev/ttyUSB0", model=STATEMENT_D2)
    assert recv.baud_rate == 19200

    captured = {}

    async def fake_open(port, *, baudrate, **kwargs):
        captured["baud"] = baudrate
        return mock_serial_gen1.reader, mock_serial_gen1.writer

    mock_serial_gen1.respond_to(b"?", b"(Statement D2,Version 3.10,Sep 1 2010)")

    with patch(
        "anthem_rs232.gen1.receiver.serialx.open_serial_connection",
        side_effect=fake_open,
    ):
        await recv.connect()

    assert captured["baud"] == 19200
    await recv.disconnect()


async def test_connect_failure_raises_connection_error(mock_serial_gen1):
    """Identify timeout becomes ConnectionError."""
    recv = Gen1Receiver("/dev/ttyUSB0", model=AVM_50)

    async def fake_open(*args, **kwargs):
        return mock_serial_gen1.reader, mock_serial_gen1.writer

    with patch(
        "anthem_rs232.gen1.receiver.serialx.open_serial_connection",
        side_effect=fake_open,
    ), pytest.raises(ConnectionError):
        await recv.connect()


async def test_connect_populates_identify(gen1):
    state = gen1.state
    assert state.model == "Statement D2"
    assert state.version == "3.10"
    assert state.build_date == "Sep 1 2010"


async def test_connect_sends_sst1(gen1, mock_serial_gen1):
    assert b"SST1\n" in mock_serial_gen1.written


# -- Control commands --------------------------------------------------------


async def test_main_power_on(gen1, mock_serial_gen1):
    await gen1.main.power_on()
    assert mock_serial_gen1.written[-1] == b"P1P1\n"


async def test_main_power_off(gen1, mock_serial_gen1):
    await gen1.main.power_off()
    assert mock_serial_gen1.written[-1] == b"P1P0\n"


async def test_zone2_power(gen1, mock_serial_gen1):
    await gen1.zone_2.power_on()
    assert mock_serial_gen1.written[-1] == b"P2P1\n"


async def test_main_set_volume(gen1, mock_serial_gen1):
    await gen1.main.set_volume(-30.5)
    assert mock_serial_gen1.written[-1] == b"P1VM-30.5\n"


async def test_zone2_set_volume(gen1, mock_serial_gen1):
    # Zone 2 volume is ``P2V`` (no ``M``) and 1.25 dB step.
    await gen1.zone_2.set_volume(-50.0)
    assert mock_serial_gen1.written[-1] == b"P2V-50.0\n"


async def test_main_mute_toggle(gen1, mock_serial_gen1):
    await gen1.main.mute_toggle()
    assert mock_serial_gen1.written[-1] == b"P1MT\n"


async def test_main_select_source(gen1, mock_serial_gen1):
    await gen1.main.select_source(Source.DVD_2.value)  # "d"
    assert mock_serial_gen1.written[-1] == b"P1Sd\n"


async def test_main_select_source_invalid_length(gen1):
    with pytest.raises(ValueError):
        await gen1.main.select_source("dvd")


async def test_main_set_decoder_mode(gen1, mock_serial_gen1):
    await gen1.main.set_decoder_mode("5", DecoderMode.PRO_LOGIC)
    assert mock_serial_gen1.written[-1] == b"P1D54\n"


async def test_main_set_effect_mode(gen1, mock_serial_gen1):
    await gen1.main.set_effect_mode("5", EffectMode.HALL)
    assert mock_serial_gen1.written[-1] == b"P1E52\n"


async def test_main_set_dolby_dynamic_range(gen1, mock_serial_gen1):
    await gen1.main.set_dolby_dynamic_range(DolbyDynamicRange.LATE_NIGHT)
    assert mock_serial_gen1.written[-1] == b"P1C2\n"


async def test_main_sleep_timer(gen1, mock_serial_gen1):
    await gen1.main.set_sleep_timer(SleepTimer.SIXTY_MIN)
    assert mock_serial_gen1.written[-1] == b"P1Z2\n"


async def test_main_display_message(gen1, mock_serial_gen1):
    await gen1.main.display_message(1, "Hello")
    assert mock_serial_gen1.written[-1] == b"P1x1Hello\n"


async def test_main_show_status(gen1, mock_serial_gen1):
    await gen1.main.show_status()
    assert mock_serial_gen1.written[-1] == b"P1s\n"


async def test_main_balance(gen1, mock_serial_gen1):
    await gen1.main.set_front_balance(2.5)
    assert mock_serial_gen1.written[-1] == b"P1LF2.5\n"


async def test_main_master_bass(gen1, mock_serial_gen1):
    await gen1.main.set_master_bass(-3.0)
    assert mock_serial_gen1.written[-1] == b"P1BM-3.0\n"


async def test_main_channel_trims(gen1, mock_serial_gen1):
    await gen1.main.set_center_trim(1.5)
    assert mock_serial_gen1.written[-1] == b"P1VC1.5\n"
    await gen1.main.set_sub_trim(-2.0)
    assert mock_serial_gen1.written[-1] == b"P1VS-2.0\n"


async def test_rec_select_source(gen1, mock_serial_gen1):
    await gen1.rec.select_source("4")
    assert mock_serial_gen1.written[-1] == b"P3S4\n"


async def test_headphone_set_volume(gen1, mock_serial_gen1):
    await gen1.headphone.set_volume(-20.0)
    assert mock_serial_gen1.written[-1] == b"HV-20.0\n"


async def test_headphone_mute(gen1, mock_serial_gen1):
    await gen1.headphone.mute_toggle()
    assert mock_serial_gen1.written[-1] == b"HMT\n"


async def test_tuner_set_fm(gen1, mock_serial_gen1):
    await gen1.tuner.set_fm_frequency(101.5)
    assert mock_serial_gen1.written[-1] == b"TFT101.5\n"


async def test_tuner_set_am(gen1, mock_serial_gen1):
    await gen1.tuner.set_am_frequency(540)
    assert mock_serial_gen1.written[-1] == b"TAT0540\n"


async def test_tuner_fm_out_of_range(gen1):
    with pytest.raises(ValueError):
        await gen1.tuner.set_fm_frequency(80.0)


async def test_set_trigger(gen1, mock_serial_gen1):
    await gen1.set_trigger(1, True)
    assert mock_serial_gen1.written[-1] == b"t1T1\n"
    await gen1.set_trigger(2, False)
    assert mock_serial_gen1.written[-1] == b"t2T0\n"


async def test_save_user_settings(gen1, mock_serial_gen1):
    await gen1.save_user_settings()
    assert mock_serial_gen1.written[-1] == b"SfSU\n"


async def test_rename_source(gen1, mock_serial_gen1):
    await gen1.rename_source("5", "Apple")
    assert mock_serial_gen1.written[-1] == b"SN5Apple\n"


async def test_rename_source_too_long(gen1):
    with pytest.raises(ValueError):
        await gen1.rename_source("5", "Way too long")


async def test_power_on_all_chains_commands(gen1, mock_serial_gen1):
    await gen1.power_on_all()
    assert mock_serial_gen1.written[-1] == b"P1P1;P2P1;P3P1\n"


# -- Queries -----------------------------------------------------------------


async def test_query_main_status(gen1, mock_serial_gen1):
    mock_serial_gen1.respond_to(b"P1?", b"P1S5V-30.5M0D0E0")
    await gen1.main.query_status()
    s = gen1.state.main_zone
    assert s.source == "5"
    assert s.volume == -30.5
    assert s.mute is False
    assert s.decoder_modes["5"] is DecoderMode.AC3


async def test_query_volume(gen1, mock_serial_gen1):
    mock_serial_gen1.respond_to(b"P1VM?", b"P1VM-25.0")
    db = await gen1.main.query_volume()
    assert db == -25.0


async def test_query_zone2_status(gen1, mock_serial_gen1):
    mock_serial_gen1.respond_to(b"P2?", b"P2S4V-50.0M1")
    await gen1.zone_2.query_status()
    s = gen1.state.zone_2
    assert s.source == "4"
    assert s.volume == -50.0
    assert s.mute is True


async def test_query_headphone_status(gen1, mock_serial_gen1):
    mock_serial_gen1.respond_to(b"H?", b"HS1V-15.0M0")
    await gen1.headphone.query_status()
    h = gen1.state.headphone
    assert h.source == "1"
    assert h.volume == -15.0


async def test_query_tuner_frequency_fm(gen1, mock_serial_gen1):
    mock_serial_gen1.respond_to(b"TT?", b"TFT101.5")
    band, freq = await gen1.tuner.query_frequency()
    assert band is TunerBand.FM
    assert freq == 101.5


async def test_query_tuner_frequency_am(gen1, mock_serial_gen1):
    mock_serial_gen1.respond_to(b"TT?", b"TAT0540")
    band, freq = await gen1.tuner.query_frequency()
    assert band is TunerBand.AM
    assert freq == 540


# -- Auto-reports / events ---------------------------------------------------


async def test_volume_event_updates_state(gen1, mock_serial_gen1):
    mock_serial_gen1.feed(b"P1VM-25.0")
    await asyncio.sleep(0)
    assert gen1.state.main_zone.volume == -25.0


async def test_main_status_event_updates_state(gen1, mock_serial_gen1):
    mock_serial_gen1.feed(b"P1S5V-20.0M0D1E0")
    await asyncio.sleep(0)
    s = gen1.state.main_zone
    assert s.source == "5"
    assert s.volume == -20.0
    assert s.decoder_modes["5"] is DecoderMode.DTS


async def test_subscriber_called_on_event(gen1, mock_serial_gen1):
    received: list = []
    unsub = gen1.subscribe(received.append)
    mock_serial_gen1.feed(b"P1V-15.0")
    await asyncio.sleep(0)
    unsub()
    assert any(s and s.main_zone.volume == -15.0 for s in received)


async def test_subscriber_receives_none_on_disconnect(gen1):
    received: list = []
    gen1.subscribe(received.append)
    await gen1.disconnect()
    assert received[-1] is None


# -- Errors -------------------------------------------------------------------


async def test_query_raises_on_invalid_command(gen1, mock_serial_gen1):
    mock_serial_gen1.respond_to(b"P1VM?", b"Invalid Command")
    with pytest.raises(Gen1CommandError):
        await gen1.main.query_volume()


async def test_query_raises_on_main_off(gen1, mock_serial_gen1):
    mock_serial_gen1.respond_to(b"P1VM?", b"Main Off")
    with pytest.raises(Gen1CommandError) as excinfo:
        await gen1.main.query_volume()
    assert excinfo.value.phrase == "Main Off"


# -- Models -------------------------------------------------------------------


def test_d2_model_defaults():
    assert STATEMENT_D2.baud_rate == 19200
    assert STATEMENT_D2.has_headphone is True
    assert STATEMENT_D2.arc is True
    assert "d" in STATEMENT_D2.source_map  # has letter-coded second-bank inputs


def test_avm_50_model_defaults():
    assert AVM_50.baud_rate == 9600
    assert AVM_50.arc is True


def test_mrx_700_model_defaults():
    assert MRX_700.baud_rate == 9600
    assert MRX_700.zones == 2
    assert MRX_700.has_headphone is False
