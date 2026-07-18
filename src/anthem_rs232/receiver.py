"""Receiver implementation for anthem_rs232."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import serialx

from .const import (
    BAUD_RATE,
    COMMAND_TIMEOUT,
    WATCHDOG_INTERVAL,
    WATCHDOG_PROBE_ATTEMPTS,
    LIP_SYNC_STEP_MS,
    MAX_DOLBY_VOLUME_LEVELER,
    MAX_INPUTS,
    MAX_LIP_SYNC_MS,
    MIN_DOLBY_VOLUME_LEVELER,
    MIN_LIP_SYNC_MS,
    TERMINATOR,
    AudioInputChannels,
    AudioInputFormat,
    AudioListeningMode,
    DolbyDynamicRange,
    FrontPanelBrightness,
    TunerStatus,
    VideoInputResolution,
    Zone,
    _RESPONSE_PREFIXES,
)
from .players import MainPlayer, ZonePlayer
from .protocol import (
    PendingQuery,
    parse_balance_param,
    parse_error_reply,
    parse_fm_frequency,
    parse_level_param,
    parse_tone_param,
    parse_volume_param,
)
from .state import InputConfig, ReceiverState, TriggerState, ZoneState

if TYPE_CHECKING:
    from .models import ReceiverModel

_LOGGER = logging.getLogger(__name__)


StateCallback = Callable[[ReceiverState | None], None]

#: Response prefixes sorted longest-first so that ``Z1IRH`` matches before ``Z1IR``.
_PREFIXES_BY_LEN = tuple(
    sorted(_RESPONSE_PREFIXES, key=lambda p: (-len(p), p))
)


class CommandError(Exception):
    """The receiver returned an error response (``!E/R/I/Z``)."""

    def __init__(self, kind: str, original: str) -> None:
        super().__init__(f"Receiver error {kind!s}: {original}")
        self.kind = kind
        self.original = original


class AnthemReceiver:
    """Async controller for an Anthem MRX 1120 / 720 / 520 / AVM 60 over RS232."""

    def __init__(
        self,
        port: str,
        model: ReceiverModel | None = None,
    ) -> None:
        self._port = port
        self._model = model
        self._reader: asyncio.StreamReader | None = None
        self._writer: serialx.SerialStreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._last_rx = 0.0
        self._state = ReceiverState()
        self.main = MainPlayer(self, self._state.main_zone)
        self.zone_2 = ZonePlayer(self, Zone.ZONE_2, self._state.zone_2)
        self._subscribers: list[StateCallback] = []
        self._pending_queries: list[PendingQuery] = []
        self._write_lock = asyncio.Lock()
        self._connected = False

    # -- Properties --

    @property
    def model(self) -> ReceiverModel | None:
        """Return the receiver model, if set."""
        return self._model

    @property
    def state(self) -> ReceiverState:
        """Return a deep copy of the current state."""
        return self._state.copy()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def power(self) -> bool | None:
        """Return the current chassis power state (any zone on)."""
        return self._state.power

    # -- Subscriptions --

    def subscribe(self, callback: StateCallback) -> Callable[[], None]:
        """Subscribe to state changes. Returns an unsubscribe function."""
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback)

    # -- Connection lifecycle --

    async def connect(self) -> None:
        """Open the serial connection, verify with Z1POW?, enable auto-reports."""
        self._reader, self._writer = await serialx.open_serial_connection(
            self._port,
            baudrate=BAUD_RATE,
        )
        self._connected = True
        self._read_task = asyncio.create_task(self._read_loop())
        self._read_task.add_done_callback(self._on_read_task_done)
        self._last_rx = time.monotonic()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        # Use Z1POW? for the verification probe -- the spec lists it (along
        # with IDM? and ZxPOWy) as one of the few commands that work even
        # while the system is in standby, and it always returns a payload.
        # Some serial proxies drop the first frame after subscribe; retry a
        # few times before giving up.
        for attempt in range(3):
            try:
                await self._query("Z1POW")
                break
            except (TimeoutError, CommandError):
                if attempt == 2:
                    await self.disconnect()
                    raise ConnectionError(
                        f"No response from receiver on {self._port}"
                    ) from None

        # Turn on auto-reports so external state changes (front panel, IR
        # remote, IP) propagate to subscribers.
        try:
            await self._send_command("ECH", "1")
        except CommandError:
            _LOGGER.debug("ECH1 rejected; continuing without auto-reports")

        _LOGGER.info("Connected to Anthem receiver on %s", self._port)

    async def disconnect(self) -> None:
        """Close the serial connection."""
        await self._teardown()
        _LOGGER.info("Disconnected from Anthem receiver")

    # -- Identification --

    async def query_model(self) -> str:
        """Query the receiver model name (IDM?)."""
        return await self._query("IDM")

    async def query_software_version(self) -> str:
        return await self._query("IDS")

    async def query_region(self) -> str:
        return await self._query("IDR")

    async def query_software_build_date(self) -> str:
        return await self._query("IDB")

    async def query_hardware_version(self) -> str:
        return await self._query("IDH")

    async def query_mac_address(self) -> str:
        return await self._query("IDN")

    # -- System power (all zones) --

    async def power_on_all(self) -> None:
        """Power on every zone (Z0POW1)."""
        await self._send_command("Z0POW", "1")

    async def power_off_all(self) -> None:
        """Power off every zone (Z0POW0). Used for system standby."""
        await self._send_command("Z0POW", "0")

    # -- Setup --

    async def set_echo(self, enabled: bool) -> None:
        """Enable or disable auto-report messages."""
        await self._send_command("ECH", "1" if enabled else "0")

    async def set_front_panel_brightness(self, level: FrontPanelBrightness) -> None:
        """Set the front panel display brightness."""
        await self._send_command("FPB", str(level.value))

    async def cycle_front_panel_brightness(self) -> None:
        """Cycle the front panel display brightness."""
        await self._send_command("FPB", "n")

    async def set_standby_ip_control(self, enabled: bool) -> None:
        """Enable or disable Standby IP Control (required for power-on via IP)."""
        await self._send_command("SIP", "1" if enabled else "0")

    async def set_speaker_profile(self, profile: int, input_index: int = 0) -> None:
        """Set the active speaker profile (1-4) for an input (0 = current)."""
        if not 1 <= profile <= 4:
            raise ValueError(f"Speaker profile must be 1-4: {profile}")
        await self._send_command("SSP", f"{input_index:02d}{profile}")

    async def query_speaker_profile_name(self, profile: int) -> str:
        """Query the configured name of speaker profile 1-4."""
        if not 1 <= profile <= 4:
            raise ValueError(f"Speaker profile must be 1-4: {profile}")
        resp = await self._query(f"SPN{profile}")
        # Response format SNPyzzzzzzzz -- but the response prefix matches our
        # query prefix SPNy, so the captured ``resp`` is the name suffix.
        return resp

    # -- Per-input processing (input 0 = the currently selected input) --

    async def set_lip_sync(self, ms: int, input_index: int = 0) -> None:
        """Set the lip sync delay in ms (0-150, 5 ms steps) for an input."""
        _validate_input_index(input_index)
        if not MIN_LIP_SYNC_MS <= ms <= MAX_LIP_SYNC_MS:
            raise ValueError(f"Lip sync out of range: {ms}")
        if ms % LIP_SYNC_STEP_MS:
            raise ValueError(f"Lip sync must be in {LIP_SYNC_STEP_MS} ms steps: {ms}")
        await self._send_command("SLIP", f"{input_index:02d}{ms:03d}")

    async def query_lip_sync(self, input_index: int = 0) -> int:
        """Query the lip sync delay in ms for an input."""
        _validate_input_index(input_index)
        return int(await self._query(f"SLIP{input_index:02d}"))

    async def set_dolby_volume(self, enabled: bool, input_index: int = 0) -> None:
        """Turn Dolby Volume off/on for an input."""
        _validate_input_index(input_index)
        await self._send_command(
            "SDVS", f"{input_index:02d}{'1' if enabled else '0'}"
        )

    async def query_dolby_volume(self, input_index: int = 0) -> bool:
        """Query whether Dolby Volume is on for an input."""
        _validate_input_index(input_index)
        return await self._query(f"SDVS{input_index:02d}") == "1"

    async def set_dolby_volume_leveler(self, level: int, input_index: int = 0) -> None:
        """Set the Dolby Volume Leveler (0 = off, 1-9) for an input."""
        _validate_input_index(input_index)
        if not MIN_DOLBY_VOLUME_LEVELER <= level <= MAX_DOLBY_VOLUME_LEVELER:
            raise ValueError(f"Dolby Volume Leveler out of range: {level}")
        await self._send_command("SDVL", f"{input_index:02d}{level}")

    async def query_dolby_volume_leveler(self, input_index: int = 0) -> int:
        """Query the Dolby Volume Leveler (0 = off, 1-9) for an input."""
        _validate_input_index(input_index)
        return int(await self._query(f"SDVL{input_index:02d}"))

    # -- Triggers --

    async def set_trigger_control(self, trigger: int, rs232_controlled: bool) -> None:
        """Set trigger 1 or 2 to menu (False) or RS-232/IP (True) control."""
        if trigger not in (1, 2):
            raise ValueError(f"Trigger must be 1 or 2: {trigger}")
        await self._send_command(
            f"R{trigger - 1}CTL", "1" if rs232_controlled else "0"
        )

    async def set_trigger(self, trigger: int, on: bool) -> None:
        """Set trigger 1 or 2 on/off (only valid when under RS-232/IP control)."""
        if trigger not in (1, 2):
            raise ValueError(f"Trigger must be 1 or 2: {trigger}")
        await self._send_command(f"R{trigger - 1}SET", "1" if on else "0")

    # -- State population --

    async def query_state(self) -> None:
        """Query identification, inputs, and per-zone state from the receiver."""
        await self._populate_identification()
        await self._populate_inputs()
        await self._populate_main_zone()
        await self._populate_zone_2()

    @property
    def _unsupported(self) -> frozenset[str]:
        if self._model is None:
            return frozenset()
        return self._model.unsupported_startup_queries

    async def _populate_identification(self) -> None:
        unsupported = self._unsupported
        for prefix in ("IDM", "IDS", "IDR", "IDB", "IDH", "IDN"):
            if prefix in unsupported:
                continue
            try:
                await self._query(prefix)
            except (TimeoutError, CommandError):
                pass
        for prefix in ("ECH", "FPB", "SIP"):
            if prefix in unsupported:
                continue
            try:
                await self._query(prefix)
            except (TimeoutError, CommandError):
                pass

    async def _populate_inputs(self) -> None:
        try:
            count_str = await self._query("ICN")
        except (TimeoutError, CommandError):
            return
        try:
            count = int(count_str)
        except ValueError:
            return
        count = min(count, MAX_INPUTS)
        for idx in range(1, count + 1):
            try:
                await self._query(f"ISN{idx:02d}")
            except (TimeoutError, CommandError):
                pass
            try:
                await self._query(f"ILN{idx:02d}")
            except (TimeoutError, CommandError):
                pass

    async def _populate_main_zone(self) -> None:
        unsupported = self._unsupported
        for prefix in (
            "Z1POW",
            "Z1INP",
            "Z1VOL",
            "Z1MUT",
            "Z1ARC",
            "Z1BAL",
            "Z1ALM",
            "Z1DYN",
            "Z1DIA",
            "Z1AIC",
            "Z1AIF",
            "Z1AIN",
            "Z1AIR",
            "Z1BRT",
            "Z1SRT",
            "Z1VIR",
            "Z1IRH",
            "Z1IRV",
            "Z1TBS",
            "T1FMS",
            "T1PSA",
        ):
            if prefix in unsupported:
                continue
            try:
                await self._query(prefix)
            except (TimeoutError, CommandError):
                pass

    async def _populate_zone_2(self) -> None:
        unsupported = self._unsupported
        for prefix in (
            "Z2POW",
            "Z2INP",
            "Z2VOL",
            "Z2MUT",
            "Z2TBS",
        ):
            if prefix in unsupported:
                continue
            try:
                await self._query(prefix)
            except (TimeoutError, CommandError):
                pass

    # -- Source probing --

    async def probe_inputs(self, count: int | None = None) -> dict[int, InputConfig]:
        """Discover configured inputs by querying ICN? + per-input names."""
        if not self._connected:
            raise ConnectionError("Not connected")

        if count is None:
            count_str = await self._query("ICN")
            try:
                count = int(count_str)
            except ValueError:
                return {}

        count = min(count, MAX_INPUTS)
        for idx in range(1, count + 1):
            try:
                await self._query(f"ISN{idx:02d}")
            except (TimeoutError, CommandError):
                pass
            try:
                await self._query(f"ILN{idx:02d}")
            except (TimeoutError, CommandError):
                pass
        return dict(self._state.inputs)

    # -- Low-level command helpers --

    async def _send_command(self, command: str, parameter: str) -> None:
        """Send a command (no response expected beyond the ``;`` ack)."""
        assert self._writer is not None
        msg = f"{command}{parameter};".encode("ascii")
        _LOGGER.debug("Sending: %s", msg)
        try:
            async with self._write_lock:
                self._writer.write(msg)
                await self._writer.drain()
        except Exception:
            _LOGGER.exception("Error writing to serial port")
            await self._teardown()
            raise

    async def _query(self, command: str) -> str:
        """Send a query (``COMMAND?;``) and wait for the response payload."""
        assert self._writer is not None
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        pending = PendingQuery(prefix=command, future=future)
        self._pending_queries.append(pending)
        try:
            msg = f"{command}?;".encode("ascii")
            _LOGGER.debug("Querying: %s", msg)
            try:
                async with self._write_lock:
                    self._writer.write(msg)
                    await self._writer.drain()
            except Exception:
                _LOGGER.exception("Error writing to serial port")
                await self._teardown()
                raise
            return await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
        finally:
            if pending in self._pending_queries:
                self._pending_queries.remove(pending)

    # -- Read loop --

    async def _teardown(self) -> None:
        """Tear down the connection after disconnect or an error."""
        if not self._connected:
            return
        self._connected = False

        current = asyncio.current_task()
        if self._read_task is not None and self._read_task is not current:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        self._read_task = None

        if self._watchdog_task is not None and self._watchdog_task is not current:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
        self._watchdog_task = None

        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

        # Resolve any pending queries with a TimeoutError to unblock callers.
        for pending in self._pending_queries:
            if not pending.future.done():
                pending.future.set_exception(TimeoutError("Connection lost"))
        self._pending_queries.clear()

        self._notify_subscribers()

    async def _read_loop(self) -> None:
        """Continuously read messages, splitting on the ``;`` terminator."""
        assert self._reader is not None
        buf = b""

        while self._connected:
            try:
                data = await self._reader.read(256)
            except Exception:
                if not self._connected:
                    return
                _LOGGER.exception("Error reading from serial port")
                await self._teardown()
                return

            if not data:
                _LOGGER.warning("Serial connection closed")
                await self._teardown()
                return

            self._last_rx = time.monotonic()
            buf += data
            while TERMINATOR in buf:
                line, buf = buf.split(TERMINATOR, 1)
                if not line:
                    continue
                message = line.decode("ascii", errors="replace").strip()
                if not message:
                    continue
                # One malformed frame must never kill the read loop: a dead
                # loop leaves a connected, subscribed session nobody drains.
                try:
                    self._process_message(message)
                except Exception:
                    _LOGGER.exception("Error processing message %r; skipping", message)

    def _on_read_task_done(self, task: asyncio.Task) -> None:
        """Tear down if the read loop ends while still connected.

        The loop should only end via teardown; anything else (an escaped
        exception, a stray cancellation) would otherwise leave a live,
        subscribed session whose data is never read.
        """
        if not self._connected:
            return
        exc = None if task.cancelled() else task.exception()
        _LOGGER.warning(
            "Read loop ended unexpectedly (%r); tearing down connection", exc
        )
        asyncio.get_running_loop().create_task(self._teardown())

    async def _watchdog_loop(self) -> None:
        """Probe the link when RX has been idle; tear down if it's dead.

        Some transports (serial-over-network proxies) can die without
        delivering EOF or an exception, leaving an idle-but-dead session.
        Z1POW? is answered even in standby, so an unanswered probe means
        the link is gone; teardown lets the owner reconnect.
        """
        while self._connected:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            if not self._connected:
                return
            if time.monotonic() - self._last_rx < WATCHDOG_INTERVAL:
                continue
            _LOGGER.debug(
                "No RX for %.0f s; probing link with Z1POW?", WATCHDOG_INTERVAL
            )
            # A unit in ECO standby consumes the first frame as wake-up, so
            # retry before declaring the link dead. An error reply counts as
            # alive: any response proves the transport works.
            for _ in range(WATCHDOG_PROBE_ATTEMPTS):
                try:
                    await self._query("Z1POW")
                    break
                except CommandError:
                    break
                except (TimeoutError, ConnectionError, OSError):
                    if not self._connected:
                        return
            else:
                _LOGGER.warning(
                    "Watchdog probes got no response; tearing down connection"
                )
                await self._teardown()
                return

    # -- Message processing --

    @staticmethod
    def _set_attr_value(target: object, attr: str, new_value: object) -> bool:
        if getattr(target, attr) == new_value:
            return False
        setattr(target, attr, new_value)
        return True

    def _set_main_value(self, attr: str, new_value: object) -> bool:
        return self._set_attr_value(self._state.main_zone, attr, new_value)

    def _set_zone2_value(self, attr: str, new_value: object) -> bool:
        return self._set_attr_value(self._state.zone_2, attr, new_value)

    def _process_message(self, message: str) -> None:
        """Parse one terminated line from the receiver."""
        _LOGGER.debug("Received: %s", message)

        error = parse_error_reply(message)
        if error is not None:
            self._dispatch_error(error.original, error.kind.value)
            return

        prefix = self._match_prefix(message)
        if prefix is None:
            _LOGGER.debug("Unhandled message: %s", message)
            return

        param = message[len(prefix) :]
        changed = self._apply_event(prefix, param)

        # Match pendings by startswith, not equality with the table prefix:
        # query prefixes may extend a table entry with an index or channel
        # (SPN1, Z1LEV3, SLIP02), and each pending gets the payload after its
        # own prefix.
        for pending in list(self._pending_queries):
            if message.startswith(pending.prefix) and not pending.future.done():
                pending.future.set_result(message[len(pending.prefix) :])

        if changed:
            self._notify_subscribers()

    @staticmethod
    def _match_prefix(message: str) -> str | None:
        for prefix in _PREFIXES_BY_LEN:
            if message.startswith(prefix):
                return prefix
        return None

    def _dispatch_error(self, original: str, kind: str) -> None:
        """Reject any pending query whose command is echoed in an error."""
        for pending in list(self._pending_queries):
            # Errors are returned as e.g. ``!RZ1VOL+50;`` -- the original
            # command (without the trailing ``?`` for queries) is echoed back.
            if (
                original.startswith(pending.prefix)
                and not pending.future.done()
            ):
                pending.future.set_exception(CommandError(kind, original))

    def _apply_event(self, prefix: str, param: str) -> bool:  # noqa: PLR0911 -- dispatcher
        """Update state from an event/response. Returns True when state changed."""
        # Identification
        if prefix == "IDM":
            return self._set_attr_value(self._state, "model", param)
        if prefix == "IDS":
            return self._set_attr_value(self._state, "software_version", param)
        if prefix == "IDR":
            return self._set_attr_value(self._state, "region", param)
        if prefix == "IDB":
            return self._set_attr_value(self._state, "software_build_date", param)
        if prefix == "IDH":
            return self._set_attr_value(self._state, "hardware_version", param)
        if prefix == "IDN":
            return self._set_attr_value(self._state, "mac_address", param)
        if prefix == "IDQ":
            # Composite identification reply -- ignore (covered by IDM/IDS/...).
            return False

        # Setup
        if prefix == "ECH":
            return self._set_attr_value(self._state, "echo_enabled", param == "1")
        if prefix == "FPB":
            try:
                return self._set_attr_value(
                    self._state,
                    "front_panel_brightness",
                    FrontPanelBrightness(int(param)),
                )
            except ValueError:
                return False
        if prefix == "SIP":
            return self._set_attr_value(self._state, "standby_ip_control", param == "1")
        if prefix == "SSP":
            # SSPxxy -- xx=input, y=profile. Only update when xx == "00" (current).
            if len(param) >= 3 and param[:2] == "00":
                try:
                    return self._set_attr_value(
                        self._state, "speaker_profile", int(param[2])
                    )
                except ValueError:
                    return False
            return False
        if prefix == "SPN":
            # SPNyzzz -- y=profile id, zzz=name.
            if not param:
                return False
            try:
                profile = int(param[0])
            except ValueError:
                return False
            name = param[1:]
            if self._state.speaker_profile_names.get(profile) == name:
                return False
            self._state.speaker_profile_names[profile] = name
            return True
        if prefix == "ICN":
            # No state mutation -- per-input ISN/ILN responses follow.
            return False
        if prefix in ("ISN", "ILN"):
            return self._update_input_name(prefix, param)

        # Power
        if prefix in ("Z1POW", "Z2POW", "Z3POW", "Z0POW"):
            return self._update_power(prefix, param)

        # Per-zone shared
        if prefix == "Z1INP":
            return self._set_main_value("input_index", _safe_int(param))
        if prefix == "Z2INP":
            return self._set_zone2_value("input_index", _safe_int(param))
        if prefix == "Z1VOL":
            return self._set_main_value("volume", _safe_volume(param))
        if prefix == "Z2VOL":
            return self._set_zone2_value("volume", _safe_volume(param))
        if prefix == "Z1MUT":
            return self._set_main_value("mute", param == "1")
        if prefix == "Z2MUT":
            return self._set_zone2_value("mute", param == "1")
        if prefix == "Z1ARC":
            return self._set_main_value("arc_enabled", param == "1")
        if prefix == "Z2ARC":
            return self._set_zone2_value("arc_enabled", param == "1")

        # Main zone only
        if prefix == "Z1BAL":
            return self._set_main_value("balance", parse_balance_param(param))
        if prefix == "Z1LEV":
            try:
                channel, db = parse_level_param(param)
            except ValueError:
                return False
            if self._state.main_zone.channel_levels.get(channel) == db:
                return False
            self._state.main_zone.channel_levels[channel] = db
            return True
        if prefix == "Z1TON":
            try:
                axis, db = parse_tone_param(param)
            except ValueError:
                return False
            attr = "bass" if axis == 0 else "treble"
            return self._set_main_value(attr, db)
        if prefix == "Z1ALM":
            try:
                return self._set_main_value(
                    "audio_listening_mode", AudioListeningMode(int(param))
                )
            except ValueError:
                return False
        if prefix == "Z1DYN":
            try:
                return self._set_main_value(
                    "dolby_dynamic_range", DolbyDynamicRange(int(param))
                )
            except ValueError:
                return False
        if prefix == "Z1DIA":
            if param in ("n", "na"):
                return self._set_main_value("dialog_normalization", None)
            try:
                return self._set_main_value("dialog_normalization", float(param))
            except ValueError:
                return False
        if prefix == "Z1SMD":
            return self._set_main_value("setup_menu_open", param == "1")
        if prefix == "Z1AIC":
            try:
                return self._set_main_value(
                    "audio_input_channels", AudioInputChannels(int(param))
                )
            except ValueError:
                return False
        if prefix == "Z1AIF":
            try:
                return self._set_main_value(
                    "audio_input_format", AudioInputFormat(int(param))
                )
            except ValueError:
                return False
        if prefix == "Z1AIN":
            return self._set_main_value("audio_input_name", param)
        if prefix == "Z1AIR":
            return self._set_main_value("audio_input_rate", param)
        if prefix == "Z1BRT":
            return self._set_main_value("audio_input_bit_rate", _safe_int(param))
        if prefix == "Z1SRT":
            return self._set_main_value("audio_input_sample_rate", _safe_int(param))
        if prefix == "Z1VIR":
            try:
                return self._set_main_value(
                    "video_input_resolution", VideoInputResolution(int(param))
                )
            except ValueError:
                return False
        if prefix == "Z1IRH":
            return self._set_main_value("video_input_horizontal", _safe_int(param))
        if prefix == "Z1IRV":
            return self._set_main_value("video_input_vertical", _safe_int(param))

        # Tuner
        if prefix == "T1FMS":
            try:
                return self._set_main_value("tuner_frequency", parse_fm_frequency(param))
            except ValueError:
                return False
        if prefix == "T1PSA":
            return self._set_main_value("tuner_preset", _safe_int(param))
        if prefix == "Z1TBS":
            try:
                return self._set_main_value("tuner_status", TunerStatus(int(param)))
            except ValueError:
                return False
        if prefix == "Z2TBS":
            try:
                return self._set_zone2_value("tuner_status", TunerStatus(int(param)))
            except ValueError:
                return False

        # Per-input processing settings
        if prefix in ("SLIP", "SDVS", "SDVL"):
            return self._update_input_setting(prefix, param)

        # Triggers
        if prefix in ("R0CTL", "R1CTL", "R0SET", "R1SET"):
            return self._update_trigger(prefix, param)

        return False

    def _update_input_name(self, prefix: str, param: str) -> bool:
        """Handle ISNyy<name> or ILNyy<name>."""
        if len(param) < 2:
            return False
        try:
            idx = int(param[:2])
        except ValueError:
            return False
        name = param[2:]
        config = self._state.inputs.get(idx)
        if config is None:
            config = InputConfig(index=idx)
            self._state.inputs[idx] = config
        attr = "short_name" if prefix == "ISN" else "long_name"
        if getattr(config, attr) == name:
            return False
        setattr(config, attr, name)
        return True

    def _update_input_setting(self, prefix: str, param: str) -> bool:
        """Handle SLIPxxyyy / SDVSxxy / SDVLxxy per-input setting events."""
        if len(param) < 3:
            return False
        try:
            idx = int(param[:2])
        except ValueError:
            return False
        if idx == 0:
            # 00 = the currently selected input.
            current = self._state.main_zone.input_index
            if current is None:
                return False
            idx = current
        value = param[2:]
        config = self._state.inputs.get(idx)
        if config is None:
            config = InputConfig(index=idx)
            self._state.inputs[idx] = config
        new_value: object
        if prefix == "SLIP":
            attr, new_value = "lip_sync_ms", _safe_int(value)
        elif prefix == "SDVS":
            attr, new_value = "dolby_volume", value == "1"
        else:  # SDVL
            attr, new_value = "dolby_volume_leveler", _safe_int(value)
        if new_value is None or getattr(config, attr) == new_value:
            return False
        setattr(config, attr, new_value)
        return True

    def _update_power(self, prefix: str, param: str) -> bool:
        """Handle Z?POW events. Z0POW updates every zone."""
        on = param == "1"
        changed = False
        if prefix in ("Z1POW", "Z0POW"):
            if self._set_attr_value(self._state.main_zone, "power", on):
                changed = True
        if prefix in ("Z2POW", "Z0POW"):
            if self._set_attr_value(self._state.zone_2, "power", on):
                changed = True
        # Update aggregate chassis power: True if any zone is on, False if none.
        zones_on = [self._state.main_zone.power, self._state.zone_2.power]
        if any(z is True for z in zones_on):
            chassis = True
        elif all(z is False for z in zones_on if z is not None):
            chassis = False
        else:
            chassis = self._state.power
        if self._set_attr_value(self._state, "power", chassis):
            changed = True
        return changed

    def _update_trigger(self, prefix: str, param: str) -> bool:
        """Handle R0/R1 trigger events."""
        trigger = int(prefix[1]) + 1  # R0 -> trigger 1
        op = prefix[2:]  # CTL or SET
        state = self._state.triggers.setdefault(trigger, TriggerState())
        if op == "CTL":
            return self._set_attr_value(state, "rs232_controlled", param == "1")
        return self._set_attr_value(state, "on", param == "1")

    def _notify_subscribers(self) -> None:
        snapshot = self._state.copy() if self._connected else None
        for callback in self._subscribers:
            try:
                callback(snapshot)
            except Exception:
                _LOGGER.exception("Error in state change callback %s", callback)


def _validate_input_index(input_index: int) -> None:
    if not 0 <= input_index <= MAX_INPUTS:
        raise ValueError(f"Input index out of range: {input_index}")


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _safe_volume(value: str) -> float | None:
    try:
        return parse_volume_param(value)
    except ValueError:
        return None
