"""Receiver implementation for the Anthem Gen 1 RS-232 protocol."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeAlias

import serialx
from serialkit import (
    CommandTimeoutError,
    DelimiterFramer,
    ProbeSpec,
    ProtocolError,
    SerialDevice,
)

from .const import (
    COMMAND_TIMEOUT,
    WATCHDOG_INTERVAL,
    WATCHDOG_PROBE_ATTEMPTS,
    HEADPHONE_VOLUME_STEP,
    MAIN_VOLUME_STEP,
    MAX_AM_FREQUENCY,
    MAX_FM_FREQUENCY,
    MIN_AM_FREQUENCY,
    MIN_FM_FREQUENCY,
    TERMINATOR,
    TRIM_STEP,
    ZONE2_TONE_STEP,
    ZONE2_VOLUME_STEP,
    DecoderMode,
    DolbyDynamicRange,
    EffectMode,
    SleepTimer,
    TunerBand,
    TunerMode,
    Zone,
)
from .protocol import (
    db_to_param,
    match_error,
    parse_am_frequency,
    parse_decoder,
    parse_effect,
    parse_fm_frequency,
    parse_headphone_mute,
    parse_headphone_status,
    parse_headphone_volume,
    parse_main_status,
    parse_mute,
    parse_power,
    parse_rec_source,
    parse_source,
    parse_trigger,
    parse_version,
    parse_volume,
    parse_zone2_status,
)
from .state import (
    Gen1ReceiverState,
    HeadphoneState,
    MainZoneState,
    RecZoneState,
    TriggerState,
    Zone2State,
)

if TYPE_CHECKING:
    from .models import Gen1ReceiverModel

_LOGGER = logging.getLogger(__name__)

StateCallback: TypeAlias = Callable[[Gen1ReceiverState | None], None]


class Gen1CommandError(ProtocolError):
    """The receiver responded with one of the verbose Gen 1 error strings."""

    def __init__(self, phrase: str) -> None:
        super().__init__(f"Receiver error: {phrase}")
        self.phrase = phrase


class Gen1Receiver(SerialDevice[Gen1ReceiverState]):
    """Async controller for an Anthem Gen 1 receiver over RS232.

    Supports Statement D1/D2/D2v, AVM 20/30/40/50/50v, and MRX 300/500/700.
    Pass a ``Gen1ReceiverModel`` so the receiver knows the correct baud rate
    and source map; defaults to a generic 9600-baud configuration.

    Built on serialkit: framing (``\\n`` terminator with inline ``;`` split,
    NUL scrub), matcher-based query correlation, the read loop, an idle-window
    watchdog, and reconnect are provided by :class:`serialkit.SerialDevice`.
    """

    framer_factory = staticmethod(lambda: DelimiterFramer(TERMINATOR, strip=b"\x00"))
    request_timeout = COMMAND_TIMEOUT
    # The ``?`` identify query is answered in any power state; any RX (incl. an
    # error reply) counts as alive. attempts covers a sleeping unit eating the
    # first frame as MCU wake-up.
    probe = ProbeSpec(
        frame=b"?" + TERMINATOR,
        idle=WATCHDOG_INTERVAL,
        attempts=WATCHDOG_PROBE_ATTEMPTS,
    )

    def __init__(
        self,
        port: str,
        model: Gen1ReceiverModel | None = None,
        *,
        baud_rate: int | None = None,
    ) -> None:
        self._port = port
        self._model = model
        if baud_rate is not None:
            self._baud_rate = baud_rate
        elif model is not None:
            self._baud_rate = model.baud_rate
        else:
            self._baud_rate = 9600
        super().__init__(self._open_connection)
        # A state object before start() so player/property reads work
        # pre-connect; serialkit rebuilds it via make_state() per connection.
        self.state = self.make_state()

        self.main = MainPlayer(self)
        self.zone_2 = Zone2Player(self)
        self.rec = RecPlayer(self)
        self.headphone = Headphone(self)
        self.tuner = Tuner(self)

    async def _open_connection(self) -> tuple[object, object]:
        return await serialx.open_serial_connection(
            self._port, baudrate=self._baud_rate
        )

    # -- Properties -------------------------------------------------------

    @property
    def model(self) -> Gen1ReceiverModel | None:
        return self._model

    @property
    def baud_rate(self) -> int:
        return self._baud_rate

    # -- serialkit lifecycle callbacks -----------------------------------

    def make_state(self) -> Gen1ReceiverState:
        return Gen1ReceiverState()

    def copy_state(self, state: Gen1ReceiverState) -> Gen1ReceiverState:
        return state.copy()

    @property
    def _state(self) -> Gen1ReceiverState:
        """The live receiver state.

        Read-through so the dispatcher and the zone players always see the
        current connection's state object (serialkit rebuilds it on reconnect).
        """
        assert self.state is not None
        return self.state

    async def on_connect(self) -> None:
        """Identify the unit, then enable Tx Status auto-reports (SST1).

        Runs on every (re)connection with frames already flowing.
        """
        try:
            await self.identify()
        except (CommandTimeoutError, Gen1CommandError):
            raise ConnectionError(
                f"No response from receiver on {self._port}"
            ) from None
        # Enable Tx Status so external state changes (front panel / IR / knob)
        # propagate as auto-report frames in the same format as our queries.
        try:
            await self.set_tx_status(True)
        except Gen1CommandError:
            _LOGGER.debug("SST1 rejected; continuing without auto-reports")

    def on_frame(self, frame: bytes) -> None:
        """Route one framed line, splitting inline ``;``-chained messages.

        Order: error -> reject the oldest pending; else apply state -> resolve
        the first pending whose matcher accepts the frame.
        """
        for part in frame.split(b";"):
            message = part.decode("ascii", errors="replace").strip()
            if not message:
                continue
            err = match_error(message)
            if err is not None:
                # Gen 1 errors carry no correlating content; reject the oldest
                # in-flight query (or log if none is pending).
                if not self.pending.reject_oldest(Gen1CommandError(err)):
                    _LOGGER.warning("Unsolicited error from receiver: %s", err)
                continue
            if self._apply_event(message):
                self.notify()
            self.pending.feed(part)

    # -- Lifecycle (aliases over serialkit start/stop) -------------------

    async def connect(self) -> None:
        """Open the serial port, identify, and enable Tx Status reports."""
        await self.start()
        _LOGGER.info("Connected to Anthem Gen 1 receiver on %s", self._port)

    async def disconnect(self) -> None:
        await self.stop()
        _LOGGER.info("Disconnected from Anthem Gen 1 receiver")

    # -- Identify --------------------------------------------------------

    async def identify(self) -> str:
        """Query the unit identity string (returns ``model,version,build``)."""
        return await self._query(b"?", parse_version)

    # -- System power ----------------------------------------------------

    async def power_on_all(self) -> None:
        """Power on every zone (sent as a single chained command line)."""
        # Chained commands let one wire write turn the whole unit on.
        await self._send(b"P1P1;P2P1;P3P1")

    async def power_off_all(self) -> None:
        """Power off every zone."""
        await self._send(b"P1P0;P2P0;P3P0")

    # -- Setup -----------------------------------------------------------

    async def set_tx_status(self, enabled: bool) -> None:
        """Enable or disable Tx Status auto-report frames (``SST``)."""
        await self._send(b"SST1" if enabled else b"SST0")

    async def set_osd(self, enabled: bool) -> None:
        """Enable or disable the on-screen display (``SOS``)."""
        await self._send(b"SOS1" if enabled else b"SOS0")

    async def lock_front_panel(self) -> None:
        await self._send(b"FPL1")

    async def unlock_front_panel(self) -> None:
        await self._send(b"FPL0")

    async def rename_source(self, source_code: str, name: str) -> None:
        """Rename a source (max 6 ASCII chars, cannot include ``;``)."""
        if len(name) > 6:
            raise ValueError("Source name must be 6 characters or fewer")
        if ";" in name:
            raise ValueError("Source name may not contain ';'")
        await self._send(f"SN{source_code}{name}".encode("ascii"))

    async def save_current_settings(self) -> None:
        await self._send(b"SfSC")

    async def save_user_settings(self) -> None:
        await self._send(b"SfSU")

    async def restore_user_settings(self) -> None:
        await self._send(b"SfLU")

    async def save_installer_settings(self) -> None:
        await self._send(b"SfSI")

    async def restore_installer_settings(self) -> None:
        await self._send(b"SfLI")

    # -- Triggers --------------------------------------------------------

    async def set_trigger(self, trigger: int, on: bool) -> None:
        """Set 12 V trigger 1/2/3 on/off (``t{N}T{0|1}``)."""
        if trigger not in (1, 2, 3):
            raise ValueError(f"Trigger must be 1, 2, or 3: {trigger}")
        await self._send(f"t{trigger}T{1 if on else 0}".encode("ascii"))

    async def query_trigger(self, trigger: int) -> bool:
        """Query trigger ``trigger`` (``t{N}T?``)."""
        if trigger not in (1, 2, 3):
            raise ValueError(f"Trigger must be 1, 2, or 3: {trigger}")
        result = await self._query(
            f"t{trigger}T?".encode("ascii"),
            lambda p: parse_trigger(p) if (parse_trigger(p) or (None,))[0] == trigger else None,
        )
        return result[1]  # type: ignore[index]

    # -- State population ------------------------------------------------

    async def query_state(self) -> None:
        """Query identity, all zones, headphone, and tuner."""
        for fn in (
            self.identify,
            self.main.query_status,
            self.zone_2.query_status,
            self.rec.query_source,
        ):
            try:
                await fn()
            except (TimeoutError, Gen1CommandError):
                pass

        if self._model is None or self._model.has_headphone:
            try:
                await self.headphone.query_status()
            except (TimeoutError, Gen1CommandError):
                pass

        if self._model is None or self._model.has_tuner:
            try:
                await self.tuner.query_frequency()
            except (TimeoutError, Gen1CommandError):
                pass

    # -- Low-level send / query -----------------------------------------

    async def _send(self, command: bytes) -> None:
        """Write a raw command to the wire (the LF terminator is appended)."""
        await self.send(command + TERMINATOR)

    async def _query(
        self,
        command: bytes,
        matcher: Callable[[str], Any | None],
        *,
        timeout: float | None = None,
    ) -> Any:
        """Send a query and wait for a frame the ``matcher`` callable accepts.

        Gen 1 matchers return a decoded value (or ``None`` for no match); the
        serialkit tracker wants a bool, so we bridge and re-run the matcher on
        the resolved frame to return its decoded value.
        """

        def accepts(frame: bytes) -> bool:
            try:
                return matcher(frame.decode("ascii", errors="replace").strip()) is not None
            except Exception:  # noqa: BLE001 - a raising matcher is a no-match
                return False

        frame = await self.request(
            command + TERMINATOR,
            accepts,
            timeout=self.request_timeout if timeout is None else timeout,
        )
        return matcher(frame.decode("ascii", errors="replace").strip())

    # -- Message processing ---------------------------------------------

    @staticmethod
    def _set_attr(target: object, attr: str, value: object) -> bool:
        if getattr(target, attr) == value:
            return False
        setattr(target, attr, value)
        return True

    def _apply_event(self, message: str) -> bool:  # noqa: PLR0911
        """Update state from a received frame. Returns True when state changed."""
        # Identify response: ``(AVM 2,Version 1.00,Jun 26 2000)``.
        info = parse_version(message)
        if info is not None:
            return self._update_identify(info)

        # Compound zone status -- check the most specific patterns first.
        main = parse_main_status(message)
        if main is not None:
            return self._apply_main_status(main)

        z2 = parse_zone2_status(message)
        if z2 is not None:
            return self._apply_zone2_status(z2)

        rec = parse_rec_source(message)
        if rec is not None:
            return self._set_attr(self._state.rec, "source", rec)

        hp = parse_headphone_status(message)
        if hp is not None:
            return self._apply_headphone_status(hp)

        # Single-field updates (P1P, P1V, P1M, P1S, P1D, P1E, ...).
        f = parse_power(message)
        if f is not None:
            return self._apply_zone_field(f.zone, "power", f.value)

        f = parse_volume(message)
        if f is not None:
            return self._apply_zone_field(f.zone, "volume", f.value)

        f = parse_mute(message)
        if f is not None:
            return self._apply_zone_field(f.zone, "mute", f.value)

        f = parse_source(message)
        if f is not None:
            return self._apply_zone_field(f.zone, "source", f.value)

        decoder = parse_decoder(message)
        if decoder is not None:
            src, mode_int = decoder
            try:
                mode = DecoderMode(mode_int)
            except ValueError:
                return False
            key = str(src)
            if self._state.main_zone.decoder_modes.get(key) == mode:
                return False
            self._state.main_zone.decoder_modes[key] = mode
            return True

        effect = parse_effect(message)
        if effect is not None:
            src, mode_int = effect
            try:
                mode = EffectMode(mode_int)
            except ValueError:
                return False
            key = str(src)
            if self._state.main_zone.effect_modes.get(key) == mode:
                return False
            self._state.main_zone.effect_modes[key] = mode
            return True

        fm = parse_fm_frequency(message)
        if fm is not None:
            tuner = self._state.tuner
            changed = self._set_attr(tuner, "fm_frequency", fm)
            if self._set_attr(tuner, "band", TunerBand.FM):
                changed = True
            return changed

        am = parse_am_frequency(message)
        if am is not None:
            tuner = self._state.tuner
            changed = self._set_attr(tuner, "am_frequency", am)
            if self._set_attr(tuner, "band", TunerBand.AM):
                changed = True
            return changed

        hpv = parse_headphone_volume(message)
        if hpv is not None:
            return self._set_attr(self._state.headphone, "volume", hpv)

        hpm = parse_headphone_mute(message)
        if hpm is not None:
            return self._set_attr(self._state.headphone, "mute", hpm)

        trig = parse_trigger(message)
        if trig is not None:
            num, on = trig
            t = self._state.triggers.setdefault(num, TriggerState())
            return self._set_attr(t, "on", on)

        _LOGGER.debug("Unhandled Gen 1 message: %s", message)
        return False

    # -- State application helpers ---------------------------------------

    def _update_identify(self, info: str) -> bool:
        """Parse ``model,version,build`` triple from the identify response."""
        changed = self._set_attr(self._state, "raw_identify", info)
        parts = [p.strip() for p in info.split(",")]
        if len(parts) >= 1 and self._set_attr(self._state, "model", parts[0]):
            changed = True
        if len(parts) >= 2:
            version = parts[1].removeprefix("Version").strip()
            if self._set_attr(self._state, "version", version):
                changed = True
        if len(parts) >= 3 and self._set_attr(self._state, "build_date", parts[2]):
            changed = True
        return changed

    def _apply_main_status(self, status) -> bool:
        mz = self._state.main_zone
        changed = False
        if self._set_attr(mz, "source", status.source):
            changed = True
        if self._set_attr(mz, "volume", status.volume):
            changed = True
        if self._set_attr(mz, "mute", status.mute):
            changed = True
        if status.decoder is not None:
            try:
                mode = DecoderMode(status.decoder)
            except ValueError:
                mode = None
            if mode is not None and mz.decoder_modes.get(status.source) != mode:
                mz.decoder_modes[status.source] = mode
                changed = True
        if status.effect is not None:
            try:
                mode = EffectMode(status.effect)
            except ValueError:
                mode = None
            if mode is not None and mz.effect_modes.get(status.source) != mode:
                mz.effect_modes[status.source] = mode
                changed = True
        return changed

    def _apply_zone2_status(self, status) -> bool:
        z2 = self._state.zone_2
        changed = False
        if self._set_attr(z2, "source", status.source):
            changed = True
        if self._set_attr(z2, "volume", status.volume):
            changed = True
        if self._set_attr(z2, "mute", status.mute):
            changed = True
        return changed

    def _apply_headphone_status(self, status) -> bool:
        h = self._state.headphone
        changed = False
        if self._set_attr(h, "source", status.source):
            changed = True
        if self._set_attr(h, "volume", status.volume):
            changed = True
        if self._set_attr(h, "mute", status.mute):
            changed = True
        return changed

    def _apply_zone_field(self, zone: int, attr: str, value: object) -> bool:
        if zone == 1:
            return self._set_attr(self._state.main_zone, attr, value)
        if zone == 2:
            return self._set_attr(self._state.zone_2, attr, value)
        if zone == 3 and attr == "source":
            return self._set_attr(self._state.rec, attr, value)
        return False

# ---------------------------------------------------------------------------
# Player abstractions
# ---------------------------------------------------------------------------


class _BaseZone:
    """Shared helpers for Main / Zone 2."""

    _zone: Zone

    def __init__(self, receiver: Gen1Receiver) -> None:
        self._receiver = receiver
        self._zone_num = self._zone.value


class MainPlayer(_BaseZone):
    """Main zone (P1) control surface."""

    _zone = Zone.MAIN

    @property
    def state(self) -> MainZoneState:
        return self._receiver._state.main_zone

    @property
    def power(self) -> bool | None:
        return self.state.power

    @property
    def volume(self) -> float | None:
        return self.state.volume

    @property
    def mute(self) -> bool | None:
        return self.state.mute

    @property
    def source(self) -> str | None:
        return self.state.source

    # -- Power --

    async def power_on(self) -> None:
        await self._receiver._send(b"P1P1")

    async def power_off(self) -> None:
        await self._receiver._send(b"P1P0")

    async def query_power(self) -> bool:
        result = await self._receiver._query(
            b"P1P?",
            lambda p: parse_power(p) if (f := parse_power(p)) and f.zone == 1 else None,
        )
        return result.value

    # -- Status --

    async def query_status(self) -> None:
        """Issue ``P1?`` and update state from the compound reply."""
        await self._receiver._query(b"P1?", parse_main_status)

    # -- Volume --

    async def set_volume(self, db: float) -> None:
        await self._receiver._send(
            f"P1VM{db_to_param(db, step=MAIN_VOLUME_STEP)}".encode("ascii")
        )

    async def volume_up(self) -> None:
        await self._receiver._send(b"P1VMU")

    async def volume_down(self) -> None:
        await self._receiver._send(b"P1VMD")

    async def query_volume(self) -> float:
        result = await self._receiver._query(
            b"P1VM?",
            lambda p: parse_volume(p) if (f := parse_volume(p)) and f.zone == 1 else None,
        )
        return result.value

    # -- Channel trims --

    async def set_center_trim(self, db: float) -> None:
        await self._receiver._send(
            f"P1VC{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_rear_trim(self, db: float) -> None:
        await self._receiver._send(
            f"P1VR{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_sub_trim(self, db: float) -> None:
        await self._receiver._send(
            f"P1VS{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_lfe_trim(self, db: float) -> None:
        await self._receiver._send(
            f"P1VL{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    # -- Balance --

    async def set_front_balance(self, db: float) -> None:
        await self._receiver._send(
            f"P1LF{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_rear_balance(self, db: float) -> None:
        await self._receiver._send(
            f"P1LR{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    # -- Tone --

    async def set_master_bass(self, db: float) -> None:
        await self._receiver._send(
            f"P1BM{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_front_bass(self, db: float) -> None:
        await self._receiver._send(
            f"P1BF{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_rear_bass(self, db: float) -> None:
        await self._receiver._send(
            f"P1BR{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_master_treble(self, db: float) -> None:
        await self._receiver._send(
            f"P1TM{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_front_treble(self, db: float) -> None:
        await self._receiver._send(
            f"P1TF{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_rear_treble(self, db: float) -> None:
        await self._receiver._send(
            f"P1TR{db_to_param(db, step=TRIM_STEP)}".encode("ascii")
        )

    async def set_tone_bypass(self, bypassed: bool) -> None:
        await self._receiver._send(b"P1TB0" if bypassed else b"P1TB1")

    # -- Mute --

    async def mute_on(self) -> None:
        await self._receiver._send(b"P1M1")

    async def mute_off(self) -> None:
        await self._receiver._send(b"P1M0")

    async def mute_toggle(self) -> None:
        await self._receiver._send(b"P1MT")

    async def query_mute(self) -> bool:
        result = await self._receiver._query(
            b"P1M?",
            lambda p: parse_mute(p) if (f := parse_mute(p)) and f.zone == 1 else None,
        )
        return result.value

    # -- Source --

    async def select_source(self, code: str) -> None:
        if len(code) != 1:
            raise ValueError("Gen 1 source code must be a single character")
        await self._receiver._send(f"P1S{code}".encode("ascii"))

    async def select_multi_source(self, video_code: str, audio_code: str) -> None:
        """``P1X{v}{a}`` -- D2/D2v independent video/audio source select."""
        await self._receiver._send(
            f"P1X{video_code}{audio_code}".encode("ascii")
        )

    async def source_seek_up(self) -> None:
        await self._receiver._send(b"P1SS+")

    async def source_seek_down(self) -> None:
        await self._receiver._send(b"P1SS-")

    # -- Decoder / effect / dynamic range --

    async def set_decoder_mode(self, source_code: str, mode: DecoderMode) -> None:
        if len(source_code) != 1:
            raise ValueError("Source code must be a single character")
        await self._receiver._send(
            f"P1D{source_code}{mode.value}".encode("ascii")
        )

    async def set_effect_mode(self, source_code: str, mode: EffectMode) -> None:
        if len(source_code) != 1:
            raise ValueError("Source code must be a single character")
        await self._receiver._send(
            f"P1E{source_code}{mode.value}".encode("ascii")
        )

    async def set_dolby_dynamic_range(self, mode: DolbyDynamicRange) -> None:
        await self._receiver._send(f"P1C{mode.value}".encode("ascii"))

    # -- Misc --

    async def show_status(self) -> None:
        """``P1s`` -- flash the front-panel/OSD status display for Main."""
        await self._receiver._send(b"P1s")

    async def display_message(self, row: int, message: str) -> None:
        """``P1x{row}{message}`` -- write an OSD message on row 1 or 2."""
        if row not in (1, 2):
            raise ValueError(f"Row must be 1 or 2: {row}")
        await self._receiver._send(
            f"P1x{row}{message}".encode("ascii")
        )

    async def set_sleep_timer(self, mode: SleepTimer) -> None:
        await self._receiver._send(f"P1Z{mode.value}".encode("ascii"))


class Zone2Player(_BaseZone):
    """Zone 2 (P2) control surface -- audio plus balance/tone, no decoder."""

    _zone = Zone.ZONE_2

    @property
    def state(self) -> Zone2State:
        return self._receiver._state.zone_2

    @property
    def power(self) -> bool | None:
        return self.state.power

    @property
    def volume(self) -> float | None:
        return self.state.volume

    @property
    def mute(self) -> bool | None:
        return self.state.mute

    @property
    def source(self) -> str | None:
        return self.state.source

    async def power_on(self) -> None:
        await self._receiver._send(b"P2P1")

    async def power_off(self) -> None:
        await self._receiver._send(b"P2P0")

    async def query_power(self) -> bool:
        result = await self._receiver._query(
            b"P2P?",
            lambda p: parse_power(p) if (f := parse_power(p)) and f.zone == 2 else None,
        )
        return result.value

    async def query_status(self) -> None:
        await self._receiver._query(b"P2?", parse_zone2_status)

    async def set_volume(self, db: float) -> None:
        await self._receiver._send(
            f"P2V{db_to_param(db, step=ZONE2_VOLUME_STEP)}".encode("ascii")
        )

    async def volume_up(self) -> None:
        await self._receiver._send(b"P2VU")

    async def volume_down(self) -> None:
        await self._receiver._send(b"P2VD")

    async def query_volume(self) -> float:
        result = await self._receiver._query(
            b"P2V?",
            lambda p: parse_volume(p) if (f := parse_volume(p)) and f.zone == 2 else None,
        )
        return result.value

    async def mute_on(self) -> None:
        await self._receiver._send(b"P2M1")

    async def mute_off(self) -> None:
        await self._receiver._send(b"P2M0")

    async def mute_toggle(self) -> None:
        await self._receiver._send(b"P2MT")

    async def select_source(self, code: str) -> None:
        if len(code) != 1:
            raise ValueError("Source code must be a single character")
        await self._receiver._send(f"P2S{code}".encode("ascii"))

    async def set_balance(self, db: float) -> None:
        await self._receiver._send(
            f"P2L{db_to_param(db, step=ZONE2_VOLUME_STEP)}".encode("ascii")
        )

    async def set_bass(self, db: float) -> None:
        await self._receiver._send(
            f"P2B{db_to_param(db, step=ZONE2_TONE_STEP)}".encode("ascii")
        )

    async def set_treble(self, db: float) -> None:
        await self._receiver._send(
            f"P2T{db_to_param(db, step=ZONE2_TONE_STEP)}".encode("ascii")
        )

    async def set_tone_bypass(self, bypassed: bool) -> None:
        await self._receiver._send(b"P2TB0" if bypassed else b"P2TB1")

    async def show_status(self) -> None:
        await self._receiver._send(b"P2s")


class RecPlayer:
    """Rec / Zone 3 (P3) -- source-only output."""

    def __init__(self, receiver: Gen1Receiver) -> None:
        self._receiver = receiver

    @property
    def state(self) -> RecZoneState:
        return self._receiver._state.rec

    @property
    def source(self) -> str | None:
        return self.state.source

    async def select_source(self, code: str) -> None:
        if len(code) != 1:
            raise ValueError("Source code must be a single character")
        await self._receiver._send(f"P3S{code}".encode("ascii"))

    async def query_source(self) -> str:
        result = await self._receiver._query(b"P3?", parse_rec_source)
        return result


class Headphone:
    """Dedicated headphone output (``H?`` / ``HV`` / ``HM``)."""

    def __init__(self, receiver: Gen1Receiver) -> None:
        self._receiver = receiver

    @property
    def state(self) -> HeadphoneState:
        return self._receiver._state.headphone

    @property
    def volume(self) -> float | None:
        return self.state.volume

    @property
    def mute(self) -> bool | None:
        return self.state.mute

    async def query_status(self) -> None:
        await self._receiver._query(b"H?", parse_headphone_status)

    async def set_volume(self, db: float) -> None:
        await self._receiver._send(
            f"HV{db_to_param(db, step=HEADPHONE_VOLUME_STEP)}".encode("ascii")
        )

    async def volume_up(self) -> None:
        await self._receiver._send(b"HVU")

    async def volume_down(self) -> None:
        await self._receiver._send(b"HVD")

    async def query_volume(self) -> float:
        return await self._receiver._query(b"HV?", parse_headphone_volume)

    async def mute_on(self) -> None:
        await self._receiver._send(b"HM1")

    async def mute_off(self) -> None:
        await self._receiver._send(b"HM0")

    async def mute_toggle(self) -> None:
        await self._receiver._send(b"HMT")

    async def query_mute(self) -> bool:
        return await self._receiver._query(b"HM?", parse_headphone_mute)

    async def set_balance(self, db: float) -> None:
        """Headphone balance attenuation (``Hb``)."""
        await self._receiver._send(
            f"Hb{db_to_param(db, step=ZONE2_VOLUME_STEP)}".encode("ascii")
        )

    async def set_treble(self, db: float) -> None:
        """Headphone treble (``HT``, +/- 14 dB in 2.0 dB steps)."""
        await self._receiver._send(
            f"HT{db_to_param(db, step=2.0)}".encode("ascii")
        )

    async def set_bass(self, db: float) -> None:
        """Headphone bass (``HB``)."""
        await self._receiver._send(
            f"HB{db_to_param(db, step=2.0)}".encode("ascii")
        )


class Tuner:
    """FM/AM tuner (``T?`` family)."""

    def __init__(self, receiver: Gen1Receiver) -> None:
        self._receiver = receiver

    async def set_fm_frequency(self, mhz: float) -> None:
        if not MIN_FM_FREQUENCY <= mhz <= MAX_FM_FREQUENCY:
            raise ValueError(f"FM frequency out of range: {mhz}")
        await self._receiver._send(f"TFT{mhz:.1f}".encode("ascii"))

    async def set_am_frequency(self, khz: int) -> None:
        if not MIN_AM_FREQUENCY <= khz <= MAX_AM_FREQUENCY:
            raise ValueError(f"AM frequency out of range: {khz}")
        await self._receiver._send(f"TAT{khz:04d}".encode("ascii"))

    async def fm_preset(self, bank: int, preset: int) -> None:
        await self._receiver._send(f"TFP{bank}{preset}".encode("ascii"))

    async def am_preset(self, bank: int, preset: int) -> None:
        await self._receiver._send(f"TAP{bank}{preset}".encode("ascii"))

    async def assign_fm_preset(self, preset_id: str, frequency: float) -> None:
        """``TFS y=zzz.z`` -- assign FM preset ``y`` to frequency ``zzz.z`` MHz."""
        await self._receiver._send(
            f"TFS{preset_id}={frequency:.1f}".encode("ascii")
        )

    async def assign_am_preset(self, preset_id: str, frequency: int) -> None:
        """``TAS y=zzzz`` -- assign AM preset ``y`` to frequency ``zzzz`` kHz."""
        await self._receiver._send(
            f"TAS{preset_id}={frequency}".encode("ascii")
        )

    async def tune_up(self) -> None:
        await self._receiver._send(b"T+")

    async def tune_down(self) -> None:
        await self._receiver._send(b"T-")

    async def set_mode(self, mode: TunerMode) -> None:
        await self._receiver._send(f"TH{mode.value}".encode("ascii"))

    async def query_frequency(self) -> tuple[TunerBand, float | int]:
        """Query the current tuner frequency. Returns (band, frequency)."""

        def matcher(p: str):
            am = parse_am_frequency(p)
            if am is not None:
                return (TunerBand.AM, am)
            fm = parse_fm_frequency(p)
            if fm is not None:
                return (TunerBand.FM, fm)
            return None

        return await self._receiver._query(b"TT?", matcher)
