"""Runtime state dataclasses for the Anthem Gen 1 protocol."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .const import (
    DecoderMode,
    DolbyDynamicRange,
    EffectMode,
    FrontPanelLock,
    SleepTimer,
    TunerBand,
    TunerMode,
)


@dataclass
class HeadphoneState:
    """Headphone state (the dedicated headphone path on D1/D2/AVM)."""

    source: str | None = None
    volume: float | None = None
    mute: bool | None = None

    def copy(self) -> HeadphoneState:
        return replace(self)


@dataclass
class RecZoneState:
    """Rec / Zone 3 state -- source-only on Gen 1."""

    source: str | None = None  # ``"0"`` means "follow Main".

    def copy(self) -> RecZoneState:
        return replace(self)


@dataclass
class Zone2State:
    """Zone 2 state (full audio: power, source, volume, mute, balance, tone)."""

    power: bool | None = None
    source: str | None = None
    volume: float | None = None
    mute: bool | None = None
    balance: float | None = None  # dB, +/- 20
    bass: float | None = None
    treble: float | None = None
    tone_bypass: bool | None = None

    def copy(self) -> Zone2State:
        return replace(self)


@dataclass
class MainZoneState:
    """Main zone (Z1) state."""

    power: bool | None = None
    source: str | None = None
    volume: float | None = None
    mute: bool | None = None

    # Channel trims (dB, +/- 10).
    center_trim: float | None = None
    rear_trim: float | None = None
    sub_trim: float | None = None
    lfe_trim: float | None = None

    # Balance (front and rear, dB, +/- 10).
    front_balance: float | None = None
    rear_balance: float | None = None

    # Tone (master/front/rear, dB, +/- 12).
    bass_master: float | None = None
    bass_front: float | None = None
    bass_rear: float | None = None
    treble_master: float | None = None
    treble_front: float | None = None
    treble_rear: float | None = None
    tone_bypass: bool | None = None

    # Decoder/effect modes -- per-source dictionaries since the receiver
    # remembers a different mode for each source.
    decoder_modes: dict[str, DecoderMode] = field(default_factory=dict)
    effect_modes: dict[str, EffectMode] = field(default_factory=dict)
    dolby_dynamic_range: DolbyDynamicRange | None = None

    sleep_timer: SleepTimer | None = None

    def copy(self) -> MainZoneState:
        return replace(
            self,
            decoder_modes=dict(self.decoder_modes),
            effect_modes=dict(self.effect_modes),
        )


@dataclass
class TunerState:
    """Shared tuner state."""

    band: TunerBand | None = None
    fm_frequency: float | None = None  # MHz, e.g. 101.5
    am_frequency: int | None = None  # kHz, e.g. 540
    fm_mode: TunerMode | None = None  # auto / mono


@dataclass
class TriggerState:
    """12 V trigger output state."""

    on: bool | None = None


@dataclass
class Gen1ReceiverState:
    """Current state of an Anthem Gen 1 receiver."""

    # Identification (returned by ``?`` query).
    model: str | None = None
    version: str | None = None
    build_date: str | None = None
    raw_identify: str | None = None  # full identify string (e.g. "AVM 2,Version 1.00,Jun 26 2000")

    # Configuration.
    tx_status_enabled: bool | None = None
    osd_enabled: bool | None = None
    front_panel_lock: FrontPanelLock | None = None

    # Source name overrides set by the user via SN{src}{name}.
    source_names: dict[str, str] = field(default_factory=dict)

    main_zone: MainZoneState = field(default_factory=MainZoneState)
    zone_2: Zone2State = field(default_factory=Zone2State)
    rec: RecZoneState = field(default_factory=RecZoneState)
    headphone: HeadphoneState = field(default_factory=HeadphoneState)
    tuner: TunerState = field(default_factory=TunerState)
    triggers: dict[int, TriggerState] = field(
        default_factory=lambda: {1: TriggerState(), 2: TriggerState(), 3: TriggerState()}
    )

    def copy(self) -> Gen1ReceiverState:
        return replace(
            self,
            source_names=dict(self.source_names),
            main_zone=self.main_zone.copy(),
            zone_2=self.zone_2.copy(),
            rec=self.rec.copy(),
            headphone=self.headphone.copy(),
            tuner=replace(self.tuner),
            triggers={k: replace(v) for k, v in self.triggers.items()},
        )
