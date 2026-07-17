"""Runtime state dataclasses for anthem_rs232."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .const import (
    AudioInputChannels,
    AudioInputFormat,
    AudioListeningMode,
    DolbyDynamicRange,
    FrontPanelBrightness,
    TunerStatus,
    VideoInputResolution,
)


@dataclass
class InputConfig:
    """A configured input on the receiver."""

    index: int
    short_name: str | None = None
    long_name: str | None = None

    # Per-input processing settings (SLIP / SDVS / SDVL).
    lip_sync_ms: int | None = None  # 0-150 ms in 5 ms steps
    dolby_volume: bool | None = None
    dolby_volume_leveler: int | None = None  # 0 = off, 1-9


@dataclass
class TriggerState:
    """State of a 12 V trigger output."""

    rs232_controlled: bool | None = None  # True if trigger is RS-232/IP controlled
    on: bool | None = None


@dataclass
class ZoneState:
    """State for a non-main zone (Zone 2 on the MRX 1120)."""

    power: bool | None = None
    input_index: int | None = None
    volume: float | None = None
    mute: bool | None = None
    arc_enabled: bool | None = None
    tuner_status: TunerStatus | None = None

    def copy(self) -> ZoneState:
        return replace(self)


@dataclass
class MainZoneState(ZoneState):
    """State for the main listening zone.

    Extends ZoneState with main-zone-only fields (balance, channel levels,
    tone, audio listening mode, detected input formats, tuner, etc.).
    """

    balance: int | None = None  # 0-100, 50 = center
    # Channel levels in dB. Keyed by ``Channel`` index (0..7).
    channel_levels: dict[int, float] = field(default_factory=dict)
    bass: float | None = None
    treble: float | None = None
    audio_listening_mode: AudioListeningMode | None = None
    dolby_dynamic_range: DolbyDynamicRange | None = None
    dialog_normalization: float | None = None  # dB; None when not applicable

    # Detected input metadata.
    audio_input_channels: AudioInputChannels | None = None
    audio_input_format: AudioInputFormat | None = None
    audio_input_name: str | None = None
    audio_input_rate: str | None = None
    audio_input_bit_rate: int | None = None  # kbps
    audio_input_sample_rate: int | None = None  # kHz
    video_input_resolution: VideoInputResolution | None = None
    video_input_horizontal: int | None = None  # pixels
    video_input_vertical: int | None = None  # pixels
    setup_menu_open: bool | None = None

    # Tuner (FM)
    tuner_frequency: float | None = None  # MHz
    tuner_preset: int | None = None  # 0 = current station not assigned

    def copy(self) -> MainZoneState:
        return replace(self, channel_levels=dict(self.channel_levels))


@dataclass
class ReceiverState:
    """Current state of the Anthem receiver."""

    # System power: True if any zone is on, False if standby. Mirrors Z0POW
    # responses but the receiver only emits per-zone power events.
    power: bool | None = None

    # Identification (populated by query_state).
    model: str | None = None
    software_version: str | None = None
    region: str | None = None
    software_build_date: str | None = None
    hardware_version: str | None = None
    mac_address: str | None = None

    # Configuration.
    echo_enabled: bool | None = None
    front_panel_brightness: FrontPanelBrightness | None = None
    standby_ip_control: bool | None = None
    speaker_profile: int | None = None  # 1-4
    speaker_profile_names: dict[int, str] = field(default_factory=dict)

    # Inputs (populated from ICN? + ISN?/ILN? during query_state).
    inputs: dict[int, InputConfig] = field(default_factory=dict)

    main_zone: MainZoneState = field(default_factory=MainZoneState)
    zone_2: ZoneState = field(default_factory=ZoneState)

    triggers: dict[int, TriggerState] = field(
        default_factory=lambda: {1: TriggerState(), 2: TriggerState()}
    )

    def copy(self) -> ReceiverState:
        return replace(
            self,
            speaker_profile_names=dict(self.speaker_profile_names),
            inputs={k: replace(v) for k, v in self.inputs.items()},
            main_zone=self.main_zone.copy(),
            zone_2=self.zone_2.copy(),
            triggers={k: replace(v) for k, v in self.triggers.items()},
        )
