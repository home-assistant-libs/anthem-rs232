"""Known Anthem receiver models supported by this protocol.

All models below speak the **Anthem Gen 2** RS-232 protocol family
(``;``-terminated, 115200 8N1, ``Z?POW`` / ``Z?VOL`` / ``Z?MUT`` / ``Z?INP``):

- ``mrx1`` series (MRX 310 / 510 / 710, ~2013-2015) -- protocol Aug 2014.
  Same core ``Zx*`` commands as ``mrx2``, but predates ``Z1TBS`` (tuner
  status) and ``SPN``/``SSP`` (speaker profile name/select). Also has AM
  tuner support (``T1AMS`` / ``T1BND``) which this library does not expose.
- ``mrx2`` series + AVM 60 (MRX 520 / 720 / 1120 + AVM 60, 2016+) --
  protocol Feb 2016. This library's primary target.

Not supported:

- **Gen 1** -- Statement D1/D2/D2v, AVM 20/30/40/50, MRX 300/500/700. Uses
  a different command syntax. See ``rsnodgrass/python-anthemav-serial``.
- **Gen 4** -- MRX 540 / 740 / 1140 + AVM 70 / 90. New ``GC*``, ``NM*``,
  ``SS*``, split ``Z1ARC*`` sub-commands; ``T1*`` tuner commands removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import AudioListeningMode


@dataclass(frozen=True)
class ReceiverModel:
    """Known capabilities of an Anthem receiver model."""

    name: str
    #: Number of zones, including the main zone (e.g. 2 = main + zone 2).
    zones: int
    #: Maximum number of input configurations the model exposes.
    max_inputs: int = 9
    #: Number of speaker profiles supported.
    speaker_profiles: int = 4
    #: Audio listening modes supported by this model.
    audio_listening_modes: frozenset[AudioListeningMode] = field(
        default_factory=frozenset
    )
    #: Maximum volume in dB advertised by the receiver.
    max_volume_db: float = 10.0
    #: Minimum volume in dB advertised by the receiver.
    min_volume_db: float = -90.0
    #: True when the model has Anthem Room Correction.
    arc: bool = True
    #: True when the model supports an FM tuner.
    has_tuner: bool = True
    #: True when the model supports an AM tuner (X10 generation only).
    has_am_tuner: bool = False
    #: True when the model supports Atmos / Dolby Surround listening modes.
    atmos: bool = True
    #: Query prefixes to skip during ``query_state()`` because the receiver
    #: does not implement them, even though the rest of the protocol matches.
    unsupported_startup_queries: frozenset[str] = frozenset()


# Audio listening modes common across the MRX x20 series.
_COMMON_ALM = frozenset(
    {
        AudioListeningMode.NONE,
        AudioListeningMode.ANTHEM_LOGIC_MOVIE,
        AudioListeningMode.ANTHEM_LOGIC_MUSIC,
        AudioListeningMode.PLIIX_MOVIE,
        AudioListeningMode.PLIIX_MUSIC,
        AudioListeningMode.NEO6_CINEMA,
        AudioListeningMode.NEO6_MUSIC,
        AudioListeningMode.ALL_CHANNEL_STEREO,
        AudioListeningMode.ALL_CHANNEL_MONO,
        AudioListeningMode.MONO,
        AudioListeningMode.MONO_ACADEMY,
        AudioListeningMode.MONO_LEFT,
        AudioListeningMode.MONO_RIGHT,
        AudioListeningMode.HIGH_BLEND,
        AudioListeningMode.DOLBY_SURROUND,
        AudioListeningMode.NEOX_CINEMA,
        AudioListeningMode.NEOX_MUSIC,
    }
)


# Commands the X10 series doesn't implement (predate the X20 generation).
# They were added in MRX software v1.1.4 (Z1TBS) and the X20 protocol (SPN/SSP).
_X10_UNSUPPORTED = frozenset({"Z1TBS", "Z2TBS", "SPN", "SSP"})


# -- X10 series (Gen2, ~2013-2015) --

MRX_310 = ReceiverModel(
    name="MRX 310",
    zones=2,
    max_inputs=8,
    audio_listening_modes=_COMMON_ALM,
    has_am_tuner=True,
    unsupported_startup_queries=_X10_UNSUPPORTED,
)

MRX_510 = ReceiverModel(
    name="MRX 510",
    zones=2,
    max_inputs=8,
    audio_listening_modes=_COMMON_ALM,
    has_am_tuner=True,
    unsupported_startup_queries=_X10_UNSUPPORTED,
)

MRX_710 = ReceiverModel(
    name="MRX 710",
    zones=2,
    max_inputs=9,
    audio_listening_modes=_COMMON_ALM,
    has_am_tuner=True,
    unsupported_startup_queries=_X10_UNSUPPORTED,
)


# -- X20 series + AVM 60 (Gen3, 2016) -- this library's primary target --

MRX_520 = ReceiverModel(
    name="MRX 520",
    zones=2,
    max_inputs=8,
    audio_listening_modes=_COMMON_ALM,
)

MRX_720 = ReceiverModel(
    name="MRX 720",
    zones=2,
    max_inputs=9,
    audio_listening_modes=_COMMON_ALM,
)

MRX_1120 = ReceiverModel(
    name="MRX 1120",
    zones=2,
    max_inputs=9,
    audio_listening_modes=_COMMON_ALM,
)

AVM_60 = ReceiverModel(
    name="AVM 60",
    zones=2,
    max_inputs=9,
    audio_listening_modes=_COMMON_ALM,
)


# -- Generic fallback --

OTHER = ReceiverModel(
    name="Other",
    zones=2,
    max_inputs=30,
    audio_listening_modes=_COMMON_ALM,
)


#: All known receiver models, for iteration.
ALL_MODELS: tuple[ReceiverModel, ...] = (
    MRX_310,
    MRX_510,
    MRX_710,
    MRX_520,
    MRX_720,
    MRX_1120,
    AVM_60,
)


#: Models keyed by identifier string, for lookup. Includes "other".
MODELS: dict[str, ReceiverModel] = {
    "mrx_310": MRX_310,
    "mrx_510": MRX_510,
    "mrx_710": MRX_710,
    "mrx_520": MRX_520,
    "mrx_720": MRX_720,
    "mrx_1120": MRX_1120,
    "avm_60": AVM_60,
    "other": OTHER,
}
