"""Player abstractions for anthem_rs232."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from .const import (
    AudioListeningMode,
    Channel,
    DolbyDynamicRange,
    ToneControl,
    Zone,
)
from .protocol import (
    balance_to_param,
    fm_frequency_to_param,
    level_to_param,
    parse_volume_param,
    tone_to_param,
    volume_to_param,
)
from .state import ZoneState

if TYPE_CHECKING:
    from .receiver import AnthemReceiver


class _BasePlayer:
    """Shared stateful control surface for a zone."""

    def __init__(self, receiver: AnthemReceiver, zone: Zone) -> None:
        if zone is Zone.ALL:
            raise ValueError("Player zone must be MAIN, ZONE_2, or ZONE_3")
        self._receiver = receiver
        self._zone = zone
        self._zone_prefix = f"Z{zone.value}"

    @property
    def _state(self) -> ZoneState:
        # Read-through to the receiver's live zone state, so a reconnect's
        # fresh state object is always used (never a stale cached reference).
        return self._receiver._zone_state(self._zone)

    @property
    def zone(self) -> Zone:
        return self._zone

    @property
    def power(self) -> bool | None:
        return self._state.power

    @property
    def input_index(self) -> int | None:
        return self._state.input_index

    @property
    def volume(self) -> float | None:
        return self._state.volume

    @property
    def mute(self) -> bool | None:
        return self._state.mute

    async def power_on(self) -> None:
        """Turn this zone on."""
        await self._receiver._send_command(f"{self._zone_prefix}POW", "1")

    async def power_off(self) -> None:
        """Turn this zone off."""
        await self._receiver._send_command(f"{self._zone_prefix}POW", "0")

    async def query_power(self) -> bool:
        """Query the power state of this zone."""
        resp = await self._receiver._query(f"{self._zone_prefix}POW")
        return resp == "1"

    async def select_input(self, index: int) -> None:
        """Select an input on this zone (1-based index)."""
        if not 1 <= index <= 99:
            raise ValueError(f"Input index out of range: {index}")
        await self._receiver._send_command(f"{self._zone_prefix}INP", f"{index:02d}")

    async def query_input(self) -> int:
        """Query the active input index for this zone."""
        resp = await self._receiver._query(f"{self._zone_prefix}INP")
        return int(resp)

    async def set_volume(self, db: float) -> None:
        """Set this zone's volume in dB (rounded to nearest valid value)."""
        await self._receiver._send_command(
            f"{self._zone_prefix}VOL", volume_to_param(db)
        )

    async def volume_up(self, step: int = 1) -> None:
        """Increase this zone's volume by ``step`` dB (0-10)."""
        if not 0 <= step <= 10:
            raise ValueError(f"Volume step out of range: {step}")
        await self._receiver._send_command(f"{self._zone_prefix}VUP", f"{step:02d}")

    async def volume_down(self, step: int = 1) -> None:
        """Decrease this zone's volume by ``step`` dB (0-10)."""
        if not 0 <= step <= 10:
            raise ValueError(f"Volume step out of range: {step}")
        await self._receiver._send_command(f"{self._zone_prefix}VDN", f"{step:02d}")

    async def query_volume(self) -> float:
        """Query the current volume for this zone."""
        resp = await self._receiver._query(f"{self._zone_prefix}VOL")
        return parse_volume_param(resp)

    async def mute_on(self) -> None:
        """Mute this zone."""
        await self._receiver._send_command(f"{self._zone_prefix}MUT", "1")

    async def mute_off(self) -> None:
        """Unmute this zone."""
        await self._receiver._send_command(f"{self._zone_prefix}MUT", "0")

    async def mute_toggle(self) -> None:
        """Toggle mute on this zone."""
        await self._receiver._send_command(f"{self._zone_prefix}MUT", "t")

    async def query_mute(self) -> bool:
        """Query the current mute state for this zone."""
        resp = await self._receiver._query(f"{self._zone_prefix}MUT")
        return resp == "1"

    async def arc_on(self) -> None:
        """Enable Anthem Room Correction on this zone (main only)."""
        await self._receiver._send_command(f"{self._zone_prefix}ARC", "1")

    async def arc_off(self) -> None:
        """Disable Anthem Room Correction on this zone."""
        await self._receiver._send_command(f"{self._zone_prefix}ARC", "0")

    async def query_arc(self) -> bool:
        """Query the ARC state for this zone."""
        resp = await self._receiver._query(f"{self._zone_prefix}ARC")
        return resp == "1"

    async def simulate_ir(self, key: int) -> None:
        """Send a simulated IR keypress (see protocol IR table)."""
        await self._receiver._send_command(f"{self._zone_prefix}SIM", f"{key:04d}")


class MainPlayer(_BasePlayer):
    """Stateful control surface for the main zone (Z1)."""

    def __init__(self, receiver: AnthemReceiver) -> None:
        super().__init__(receiver, Zone.MAIN)

    # -- Balance --

    async def set_balance(self, percent: int) -> None:
        """Set balance: 0 = full left, 50 = center, 100 = full right."""
        await self._receiver._send_command("Z1BAL", balance_to_param(percent))

    async def balance_left(self, percent: int) -> None:
        """Shift balance toward the left by ``percent`` (0-100)."""
        await self._receiver._send_command("Z1BLT", balance_to_param(percent))

    async def balance_right(self, percent: int) -> None:
        """Shift balance toward the right by ``percent`` (0-100)."""
        await self._receiver._send_command("Z1BRT", balance_to_param(percent))

    async def query_balance(self) -> int:
        """Query the current balance percentage (0-100)."""
        return int(await self._receiver._query("Z1BAL"))

    # -- Channel levels --

    async def set_channel_level(self, channel: Channel, db: float) -> None:
        """Set a per-channel level in dB. Subs/fronts/etc. -10..+10; LFE -10..0."""
        await self._receiver._send_command(
            "Z1LEV", level_to_param(channel.value, db)
        )

    async def channel_level_up(self, channel: Channel, step: int = 1) -> None:
        """Increase a channel's level by ``step`` dB (0-10)."""
        if not 0 <= step <= 10:
            raise ValueError(f"Level step out of range: {step}")
        await self._receiver._send_command(
            "Z1LUP", f"{channel.value}{step:02d}"
        )

    async def channel_level_down(self, channel: Channel, step: int = 1) -> None:
        """Decrease a channel's level by ``step`` dB (0-10)."""
        if not 0 <= step <= 10:
            raise ValueError(f"Level step out of range: {step}")
        await self._receiver._send_command(
            "Z1LDN", f"{channel.value}{step:02d}"
        )

    async def query_channel_level(self, channel: Channel) -> float:
        """Query a single channel's level."""
        resp = await self._receiver._query(f"Z1LEV{channel.value}")
        # Response is Z1LEVy + szz, so resp is the szz portion when matched
        # against the Z1LEV prefix. The receiver returns ``yszz``; we strip
        # the leading channel id.
        if len(resp) > 0 and resp[0].isdigit():
            return parse_volume_param(resp[1:])
        return parse_volume_param(resp)

    # -- Tone --

    async def set_bass(self, db: float) -> None:
        """Set bass tone in dB."""
        await self._receiver._send_command(
            "Z1TON", tone_to_param(ToneControl.BASS.value, db)
        )

    async def set_treble(self, db: float) -> None:
        """Set treble tone in dB."""
        await self._receiver._send_command(
            "Z1TON", tone_to_param(ToneControl.TREBLE.value, db)
        )

    async def bass_up(self, step: int = 1) -> None:
        """Increase bass by ``step`` dB."""
        await self._receiver._send_command(
            "Z1TUP", f"{ToneControl.BASS.value}{step:02d}"
        )

    async def bass_down(self, step: int = 1) -> None:
        """Decrease bass by ``step`` dB."""
        await self._receiver._send_command(
            "Z1TDN", f"{ToneControl.BASS.value}{step:02d}"
        )

    async def treble_up(self, step: int = 1) -> None:
        """Increase treble by ``step`` dB."""
        await self._receiver._send_command(
            "Z1TUP", f"{ToneControl.TREBLE.value}{step:02d}"
        )

    async def treble_down(self, step: int = 1) -> None:
        """Decrease treble by ``step`` dB."""
        await self._receiver._send_command(
            "Z1TDN", f"{ToneControl.TREBLE.value}{step:02d}"
        )

    # -- Audio listening mode --

    async def set_audio_listening_mode(self, mode: AudioListeningMode) -> None:
        """Set the audio listening mode."""
        await self._receiver._send_command("Z1ALM", f"{mode.value:02d}")

    async def audio_listening_mode_next(self) -> None:
        """Cycle to the next applicable audio listening mode."""
        await self._receiver._send_command("Z1ALM", "na")

    async def audio_listening_mode_previous(self) -> None:
        """Cycle to the previous applicable audio listening mode."""
        await self._receiver._send_command("Z1ALM", "pa")

    async def query_audio_listening_mode(self) -> AudioListeningMode:
        """Query the active audio listening mode."""
        resp = await self._receiver._query("Z1ALM")
        return AudioListeningMode(int(resp))

    # -- Dolby --

    async def set_dolby_dynamic_range(self, mode: DolbyDynamicRange) -> None:
        """Set Dolby Digital dynamic range."""
        await self._receiver._send_command("Z1DYN", str(mode.value))

    async def cycle_dolby_dynamic_range(self) -> None:
        """Cycle Dolby Digital dynamic range to the next mode."""
        await self._receiver._send_command("Z1DYN", "n")

    # -- Setup menu / OSD --

    async def open_setup_menu(self) -> None:
        await self._receiver._send_command("Z1SMD", "1")

    async def close_setup_menu(self) -> None:
        await self._receiver._send_command("Z1SMD", "0")

    async def toggle_setup_menu(self) -> None:
        await self._receiver._send_command("Z1SMD", "t")

    async def display_message(self, row: int, message: str) -> None:
        """Display an OSD message on ``row`` (0 or 1)."""
        if row not in (0, 1):
            raise ValueError(f"Row must be 0 or 1: {row}")
        await self._receiver._send_command("Z1MSG", f"{row}{message}")

    # -- Tuner --

    async def tune_up(self) -> None:
        await self._receiver._send_command("T1TUP", "")

    async def tune_down(self) -> None:
        await self._receiver._send_command("T1TDN", "")

    async def seek_up(self) -> None:
        await self._receiver._send_command("T1KUP", "")

    async def seek_down(self) -> None:
        await self._receiver._send_command("T1KDN", "")

    async def preset_up(self) -> None:
        await self._receiver._send_command("T1PUP", "")

    async def preset_down(self) -> None:
        await self._receiver._send_command("T1PDN", "")

    async def set_fm_frequency(self, mhz: float) -> None:
        """Set the FM tuner frequency (87.50-108.00 MHz)."""
        await self._receiver._send_command("T1FMS", fm_frequency_to_param(mhz))

    async def query_fm_frequency(self) -> float:
        """Query the current FM frequency."""
        resp = await self._receiver._query("T1FMS")
        return float(resp)

    async def select_preset(self, preset: int) -> None:
        """Select tuner preset 1-30."""
        if not 1 <= preset <= 30:
            raise ValueError(f"Preset out of range: {preset}")
        await self._receiver._send_command("T1PSL", f"{preset:02d}")

    async def assign_preset(self, preset: int) -> None:
        """Assign the current station to preset 1-30."""
        if not 1 <= preset <= 30:
            raise ValueError(f"Preset out of range: {preset}")
        await self._receiver._send_command("T1PSA", f"{preset:02d}")

    async def remove_preset(self, preset: int) -> None:
        """Remove preset (0 removes current station from all presets)."""
        if not 0 <= preset <= 30:
            raise ValueError(f"Preset out of range: {preset}")
        await self._receiver._send_command("T1PRM", f"{preset:02d}")


class ZonePlayer(_BasePlayer):
    """Stateful control surface for a non-main zone (Zone 2)."""


AnthemPlayer: TypeAlias = MainPlayer | ZonePlayer
