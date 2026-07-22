"""Tests for anthem_rs232 query, control, and event handling."""

import asyncio
from unittest.mock import patch

import pytest

import anthem_rs232.receiver as anthem_receiver

from conftest import (
    DEFAULT_QUERY_RESPONSES,
    connect_with_defaults,
)

from anthem_rs232 import (
    AnthemReceiver,
    AudioInputChannels,
    AudioInputFormat,
    AudioListeningMode,
    Channel,
    CommandError,
    DolbyDynamicRange,
    ErrorKind,
    FrontPanelBrightness,
    InputConfig,
    TunerStatus,
    VideoInputResolution,
    _balance_to_param,
    _level_to_param,
    _parse_balance_param,
    _parse_error_reply,
    _parse_fm_frequency,
    _parse_level_param,
    _parse_tone_param,
    _parse_volume_param,
    _tone_to_param,
    _volume_to_param,
)


# -- Volume conversion --


def test_parse_volume_negative():
    assert _parse_volume_param("-35") == -35.0


def test_parse_volume_positive():
    assert _parse_volume_param("+05") == 5.0


def test_parse_volume_zero():
    assert _parse_volume_param("+00") == 0.0


def test_parse_volume_three_digit():
    assert _parse_volume_param("-100") == -100.0


def test_parse_volume_invalid():
    with pytest.raises(ValueError):
        _parse_volume_param("abc")


def test_volume_to_param_negative():
    assert _volume_to_param(-35.0) == "-35"


def test_volume_to_param_positive():
    assert _volume_to_param(5.0) == "+05"


def test_volume_to_param_zero():
    assert _volume_to_param(0.0) == "+00"


def test_volume_to_param_rounds():
    # Spec: "Entry is rounded to nearest valid value".
    assert _volume_to_param(-35.4) == "-35"
    assert _volume_to_param(-35.6) == "-36"


def test_volume_roundtrip():
    for db in [-90, -35, -10, 0, 5, 10]:
        assert _parse_volume_param(_volume_to_param(db)) == db


# -- Level / tone --


def test_parse_level_param():
    assert _parse_level_param("1+01") == (1, 1.0)
    assert _parse_level_param("0-10") == (0, -10.0)


def test_level_to_param():
    assert _level_to_param(1, 1.0) == "1+01"
    assert _level_to_param(0, -10.0) == "0-10"


def test_parse_tone_param():
    assert _parse_tone_param("0-01") == (0, -1.0)
    assert _parse_tone_param("1+05") == (1, 5.0)


def test_tone_to_param():
    assert _tone_to_param(0, -1.0) == "0-01"
    assert _tone_to_param(1, 5.0) == "1+05"


# -- Balance --


def test_parse_balance():
    assert _parse_balance_param("050") == 50


def test_balance_to_param():
    assert _balance_to_param(50) == "050"
    assert _balance_to_param(0) == "000"
    assert _balance_to_param(100) == "100"


def test_balance_to_param_out_of_range():
    with pytest.raises(ValueError):
        _balance_to_param(101)


# -- Tuner --


def test_parse_fm_frequency():
    assert _parse_fm_frequency("100.10") == 100.10


# -- Error replies --


def test_parse_error_reply_invalid():
    err = _parse_error_reply("!IHELLO")
    assert err is not None
    assert err.kind is ErrorKind.INVALID
    assert err.original == "HELLO"


def test_parse_error_reply_out_of_range():
    err = _parse_error_reply("!RZ1VOL+50")
    assert err is not None
    assert err.kind is ErrorKind.OUT_OF_RANGE
    assert err.original == "Z1VOL+50"


def test_parse_error_reply_not_an_error():
    assert _parse_error_reply("Z1POW1") is None


# -- Connect / state population --


async def test_connect_populates_state(receiver):
    state = receiver.state
    assert state.model == "MRX 1120"
    assert state.software_version == "0.2.3"
    assert state.region == "US"
    assert state.mac_address == "7CB77B014FE5"
    assert state.echo_enabled is True
    assert state.front_panel_brightness is FrontPanelBrightness.MEDIUM
    assert state.standby_ip_control is True
    assert state.power is True

    mz = state.main_zone
    assert mz.power is True
    assert mz.input_index == 1
    assert mz.volume == -35.0
    assert mz.mute is False
    assert mz.arc_enabled is True
    assert mz.balance == 50
    assert mz.audio_listening_mode is AudioListeningMode.NONE
    assert mz.dolby_dynamic_range is DolbyDynamicRange.NORMAL
    assert mz.audio_input_channels is AudioInputChannels.SEVEN_ONE
    assert mz.audio_input_format is AudioInputFormat.DOLBY
    assert mz.audio_input_name == "DTS Master Audio"
    assert mz.audio_input_rate == "48 kHz"
    assert mz.audio_input_bit_rate == 0
    assert mz.audio_input_sample_rate == 48
    assert mz.video_input_resolution is VideoInputResolution.P1080_60
    assert mz.video_input_horizontal == 1920
    assert mz.video_input_vertical == 1080
    assert mz.tuner_status is TunerStatus.OFF
    assert mz.tuner_frequency == 100.10

    assert state.zone_2.power is False
    assert state.zone_2.volume == -50.0


async def test_inputs_populated(receiver):
    inputs = receiver.state.inputs
    assert inputs[1] == InputConfig(
        index=1, short_name="CBL", long_name="Cable Box"
    )
    assert inputs[2] == InputConfig(
        index=2, short_name="BD", long_name="Blu-ray Player"
    )
    assert inputs[3].long_name == "Game Console"


async def test_connect_failure_raises_connection_error(mock_serial):
    """If IDM? is not answered, connect() raises ConnectionError."""
    recv = AnthemReceiver("/dev/ttyUSB0")
    # Empty responses => timeout on IDM?.
    mock_serial._query_responses = {}

    async def fake_open(*args, **kwargs):
        return mock_serial.reader, mock_serial.writer

    with patch(
        "anthem_rs232.receiver.serialx.open_serial_connection",
        side_effect=fake_open,
    ), pytest.raises(ConnectionError):
        await recv.connect()


# -- Control commands --


async def test_main_power_on(receiver, mock_serial):
    await receiver.main.power_on()
    assert mock_serial.written_data[-1] == b"Z1POW1;"


async def test_main_power_off(receiver, mock_serial):
    await receiver.main.power_off()
    assert mock_serial.written_data[-1] == b"Z1POW0;"


async def test_zone2_power_on(receiver, mock_serial):
    await receiver.zone_2.power_on()
    assert mock_serial.written_data[-1] == b"Z2POW1;"


async def test_select_input(receiver, mock_serial):
    await receiver.main.select_input(2)
    assert mock_serial.written_data[-1] == b"Z1INP02;"


async def test_select_input_out_of_range(receiver):
    with pytest.raises(ValueError):
        await receiver.main.select_input(0)
    with pytest.raises(ValueError):
        await receiver.main.select_input(100)


async def test_set_volume(receiver, mock_serial):
    await receiver.main.set_volume(-30.0)
    assert mock_serial.written_data[-1] == b"Z1VOL-30;"


async def test_set_volume_positive(receiver, mock_serial):
    await receiver.main.set_volume(5.0)
    assert mock_serial.written_data[-1] == b"Z1VOL+05;"


async def test_volume_up(receiver, mock_serial):
    await receiver.main.volume_up()
    assert mock_serial.written_data[-1] == b"Z1VUP01;"


async def test_volume_up_step(receiver, mock_serial):
    await receiver.main.volume_up(step=5)
    assert mock_serial.written_data[-1] == b"Z1VUP05;"


async def test_volume_up_out_of_range(receiver):
    with pytest.raises(ValueError):
        await receiver.main.volume_up(step=11)


async def test_mute_on(receiver, mock_serial):
    await receiver.main.mute_on()
    assert mock_serial.written_data[-1] == b"Z1MUT1;"


async def test_mute_toggle(receiver, mock_serial):
    await receiver.main.mute_toggle()
    assert mock_serial.written_data[-1] == b"Z1MUTt;"


async def test_set_balance(receiver, mock_serial):
    await receiver.main.set_balance(75)
    assert mock_serial.written_data[-1] == b"Z1BAL075;"


async def test_set_channel_level(receiver, mock_serial):
    await receiver.main.set_channel_level(Channel.FRONTS, 1.0)
    assert mock_serial.written_data[-1] == b"Z1LEV1+01;"


async def test_set_bass(receiver, mock_serial):
    await receiver.main.set_bass(-2.0)
    assert mock_serial.written_data[-1] == b"Z1TON0-02;"


async def test_set_treble(receiver, mock_serial):
    await receiver.main.set_treble(3.0)
    assert mock_serial.written_data[-1] == b"Z1TON1+03;"


async def test_set_audio_listening_mode(receiver, mock_serial):
    await receiver.main.set_audio_listening_mode(AudioListeningMode.DOLBY_SURROUND)
    assert mock_serial.written_data[-1] == b"Z1ALM14;"


async def test_set_fm_frequency(receiver, mock_serial):
    await receiver.main.set_fm_frequency(105.50)
    assert mock_serial.written_data[-1] == b"T1FMS105.50;"


async def test_select_preset(receiver, mock_serial):
    await receiver.main.select_preset(7)
    assert mock_serial.written_data[-1] == b"T1PSL07;"


async def test_select_preset_out_of_range(receiver):
    with pytest.raises(ValueError):
        await receiver.main.select_preset(0)
    with pytest.raises(ValueError):
        await receiver.main.select_preset(31)


async def test_arc_on(receiver, mock_serial):
    await receiver.main.arc_on()
    assert mock_serial.written_data[-1] == b"Z1ARC1;"


async def test_set_front_panel_brightness(receiver, mock_serial):
    await receiver.set_front_panel_brightness(FrontPanelBrightness.HIGH)
    assert mock_serial.written_data[-1] == b"FPB3;"


async def test_set_speaker_profile(receiver, mock_serial):
    await receiver.set_speaker_profile(2, input_index=0)
    assert mock_serial.written_data[-1] == b"SSP002;"


async def test_set_trigger(receiver, mock_serial):
    await receiver.set_trigger(1, on=True)
    assert mock_serial.written_data[-1] == b"R0SET1;"
    await receiver.set_trigger(2, on=False)
    assert mock_serial.written_data[-1] == b"R1SET0;"


async def test_simulate_ir(receiver, mock_serial):
    await receiver.main.simulate_ir(27)  # Mute toggle
    assert mock_serial.written_data[-1] == b"Z1SIM0027;"


# -- Queries --


async def test_query_volume(receiver, mock_serial):
    mock_serial._query_responses["Z1VOL"] = ["Z1VOL-25"]
    db = await receiver.main.query_volume()
    assert db == -25.0


async def test_query_input(receiver, mock_serial):
    mock_serial._query_responses["Z1INP"] = ["Z1INP05"]
    idx = await receiver.main.query_input()
    assert idx == 5


async def test_query_audio_listening_mode(receiver, mock_serial):
    mock_serial._query_responses["Z1ALM"] = ["Z1ALM14"]
    mode = await receiver.main.query_audio_listening_mode()
    assert mode is AudioListeningMode.DOLBY_SURROUND


# -- Events / auto-reports --


async def test_volume_event_updates_state(receiver, mock_serial):
    mock_serial.inject_response("Z1VOL-20")
    await asyncio.sleep(0)
    assert receiver.state.main_zone.volume == -20.0


async def test_input_event_updates_state(receiver, mock_serial):
    mock_serial.inject_response("Z1INP07")
    await asyncio.sleep(0)
    assert receiver.state.main_zone.input_index == 7


async def test_zone2_power_event(receiver, mock_serial):
    mock_serial.inject_response("Z2POW1")
    await asyncio.sleep(0)
    assert receiver.state.zone_2.power is True


async def test_z0pow_event_updates_all_zones(receiver, mock_serial):
    # Force both zones off first.
    mock_serial.inject_response("Z1POW0")
    mock_serial.inject_response("Z2POW0")
    await asyncio.sleep(0)
    mock_serial.inject_response("Z0POW1")
    await asyncio.sleep(0)
    assert receiver.state.main_zone.power is True
    assert receiver.state.zone_2.power is True
    assert receiver.state.power is True


async def test_subscriber_called_on_event(receiver, mock_serial):
    received: list = []
    unsub = receiver.subscribe(received.append)
    mock_serial.inject_response("Z1VOL-10")
    await asyncio.sleep(0.01)  # let the dispatch turn + coalesced notify flush
    unsub()
    assert any(s and s.main_zone.volume == -10.0 for s in received)


async def test_subscriber_receives_none_on_disconnect(receiver):
    received: list = []
    receiver.subscribe(received.append)
    await receiver.disconnect()
    assert received[-1] is None


# -- Error responses --


async def test_query_raises_command_error_on_out_of_range(receiver, mock_serial):
    """A query that the receiver answers with !R must raise CommandError."""
    # Inject an error response when we query Z1VOL.
    captured: list[str] = []

    def handler(cmd: str) -> None:
        captured.append(cmd)

    # Override default auto-response so the query gets only an error.
    mock_serial._query_responses["Z1VOL"] = []

    async def query_then_error():
        # Schedule the error response after the query goes out.
        await asyncio.sleep(0)
        mock_serial.inject_response("!RZ1VOL?")

    task = asyncio.create_task(query_then_error())
    with pytest.raises(CommandError):
        await receiver.main.query_volume()
    await task


async def test_dialog_normalization_not_applicable(receiver, mock_serial):
    mock_serial.inject_response("Z1DIAna")
    await asyncio.sleep(0)
    assert receiver.state.main_zone.dialog_normalization is None


# -- Model-aware query_state() --


async def test_x10_model_skips_unsupported_queries(mock_serial):
    """When a model declares unsupported queries, query_state must skip them."""
    from anthem_rs232.models import MRX_710

    recv = await connect_with_defaults(mock_serial, model=MRX_710)
    sent = b"".join(mock_serial.written_data)
    assert b"Z1TBS?;" not in sent
    assert b"Z2TBS?;" not in sent
    assert b"SPN" not in sent
    assert b"SSP" not in sent
    # Sanity: still queried the core commands.
    assert b"Z1POW?;" in sent
    assert b"Z1VOL?;" in sent
    await recv.disconnect()


# -- Per-input processing (SLIP / SDVS / SDVL) --


async def test_set_lip_sync(receiver, mock_serial):
    await receiver.set_lip_sync(50)
    assert mock_serial.written_data[-1] == b"SLIP00050;"
    await receiver.set_lip_sync(150, input_index=3)
    assert mock_serial.written_data[-1] == b"SLIP03150;"


async def test_set_lip_sync_validation(receiver, mock_serial):
    with pytest.raises(ValueError):
        await receiver.set_lip_sync(155)
    with pytest.raises(ValueError):
        await receiver.set_lip_sync(-5)
    with pytest.raises(ValueError):
        await receiver.set_lip_sync(52)  # off the 5 ms grid
    with pytest.raises(ValueError):
        await receiver.set_lip_sync(50, input_index=31)


async def test_set_dolby_volume(receiver, mock_serial):
    await receiver.set_dolby_volume(True)
    assert mock_serial.written_data[-1] == b"SDVS001;"
    await receiver.set_dolby_volume(False, input_index=2)
    assert mock_serial.written_data[-1] == b"SDVS020;"


async def test_set_dolby_volume_leveler(receiver, mock_serial):
    await receiver.set_dolby_volume_leveler(5)
    assert mock_serial.written_data[-1] == b"SDVL005;"
    await receiver.set_dolby_volume_leveler(9, input_index=2)
    assert mock_serial.written_data[-1] == b"SDVL029;"
    with pytest.raises(ValueError):
        await receiver.set_dolby_volume_leveler(10)


async def test_query_per_input_processing(receiver, mock_serial):
    mock_serial._query_responses["SLIP02"] = ["SLIP02050"]
    mock_serial._query_responses["SDVS02"] = ["SDVS021"]
    mock_serial._query_responses["SDVL02"] = ["SDVL024"]
    assert await receiver.query_lip_sync(input_index=2) == 50
    assert await receiver.query_dolby_volume(input_index=2) is True
    assert await receiver.query_dolby_volume_leveler(input_index=2) == 4
    # Query replies also update per-input state.
    config = receiver.state.inputs[2]
    assert config.lip_sync_ms == 50
    assert config.dolby_volume is True
    assert config.dolby_volume_leveler == 4


async def test_per_input_setting_events(receiver, mock_serial):
    mock_serial.inject_response("SLIP03100")
    mock_serial.inject_response("SDVS031")
    mock_serial.inject_response("SDVL037")
    await asyncio.sleep(0)
    config = receiver.state.inputs[3]
    assert config.lip_sync_ms == 100
    assert config.dolby_volume is True
    assert config.dolby_volume_leveler == 7


async def test_per_input_setting_event_current_input(receiver, mock_serial):
    # Input 00 = the currently selected input (input 1 after query_state).
    assert receiver.state.main_zone.input_index == 1
    mock_serial.inject_response("SLIP00025")
    await asyncio.sleep(0)
    assert receiver.state.inputs[1].lip_sync_ms == 25


async def test_per_input_setting_event_notifies_subscribers(receiver, mock_serial):
    states = []
    receiver.subscribe(states.append)
    mock_serial.inject_response("SDVS021")
    await asyncio.sleep(0.01)  # let the dispatch turn + coalesced notify flush
    assert states
    assert states[-1].inputs[2].dolby_volume is True


async def test_query_speaker_profile_name(receiver, mock_serial):
    # Regression: pendings whose prefix extends a table entry (SPNy, SLIPxx)
    # must still resolve.
    mock_serial._query_responses["SPN2"] = ["SPN2Movie Night"]
    assert await receiver.query_speaker_profile_name(2) == "Movie Night"


# -- Read-loop resilience --


async def test_malformed_frame_does_not_kill_read_loop(receiver, mock_serial):
    calls = []
    orig = receiver._apply_event

    def boom(prefix, param):
        if not calls:
            calls.append(1)
            raise ValueError("boom")
        return orig(prefix, param)

    receiver._apply_event = boom
    mock_serial.inject_response("Z1VOL-20")  # raises inside processing
    mock_serial.inject_response("Z1VOL-30")  # must still be processed
    await asyncio.sleep(0.01)
    # serialkit hardens on_frame: the crash is recorded, the dispatch task
    # survives, and the next frame still routes.
    assert receiver.connected
    assert receiver.frame_errors  # the boom was recorded, not fatal
    assert receiver.state.main_zone.volume == -30.0


async def test_link_loss_notifies_subscribers_none(receiver, mock_serial):
    """A dropped link (EOF) tears the session down and delivers a None
    snapshot; serialkit owns the reconnect loop from there."""
    states: list = []
    receiver.subscribe(states.append)
    mock_serial.reader.feed_eof()
    await asyncio.sleep(0.05)
    assert receiver.connected is False
    assert states[-1] is None


async def test_watchdog_probes_z1pow_when_idle(mock_serial):
    """serialkit's idle watchdog sends the Z1POW? probe; an answered probe
    (any RX counts as alive, including an error reply) keeps the link up.

    The probe mechanism (idle windows, unanswered -> reconnect) is covered by
    serialkit's own suite; this pins anthem's probe config and wiring.
    """
    from serialkit import ProbeSpec

    recv = AnthemReceiver("/dev/ttyUSB0")
    # Short idle so the watchdog fires quickly (the class default is 60 s).
    recv.probe = ProbeSpec(frame=b"Z1POW?;", idle=0.05, attempts=3)
    mock_serial._query_responses = dict(DEFAULT_QUERY_RESPONSES)

    async def fake_open(*args, **kwargs):
        return mock_serial.reader, mock_serial.writer

    with patch(
        "anthem_rs232.receiver.serialx.open_serial_connection",
        side_effect=fake_open,
    ):
        await recv.connect()
        # Ignore the connect-time Z1POW? verify; from here only the idle
        # watchdog should write, so the assertion validates the watchdog.
        mock_serial.written_data.clear()
        await asyncio.sleep(0.2)  # several idle windows
        assert recv.connected  # answered probes -> never declared dead
        assert any(w == b"Z1POW?;" for w in mock_serial.written_data)
        await recv.disconnect()


async def test_watchdog_quiet_while_traffic_flows(mock_serial):
    anthem_receiver.WATCHDOG_INTERVAL = 0.06
    try:
        recv = await connect_with_defaults(mock_serial)
        mock_serial._query_responses.clear()
        mock_serial.written_data.clear()
        for _ in range(10):
            mock_serial.inject_response("Z1VOL-31")
            await asyncio.sleep(0.02)
        assert recv.connected
        assert b"Z1POW?;" not in mock_serial.written_data
        await recv.disconnect()
    finally:
        anthem_receiver.WATCHDOG_INTERVAL = 60.0


# -- Standby NUL noise --


async def test_stray_nul_does_not_corrupt_next_frame(receiver, mock_serial):
    """ECO standby emits a stray NUL ~1 s after responses; it must not glue
    onto the next frame and break prefix matching."""
    mock_serial.reader.feed_data(b"\x00")
    mock_serial.inject_response("Z1VOL-27")
    await asyncio.sleep(0)
    assert receiver.state.main_zone.volume == -27.0


async def test_query_resolves_despite_stale_nul(receiver, mock_serial):
    """Wire-observed failure: pending Z1POW? timed out even though the
    receiver answered, because a stale NUL prefixed the reply."""
    mock_serial.reader.feed_data(b"\x00")
    mock_serial._query_responses["Z1POW"] = ["Z1POW0"]
    assert await receiver.main.query_power() is False


async def test_nul_inside_chunk_is_stripped(receiver, mock_serial):
    mock_serial.reader.feed_data(b"\x00Z1VOL-28;\x00")
    await asyncio.sleep(0)
    assert receiver.state.main_zone.volume == -28.0
