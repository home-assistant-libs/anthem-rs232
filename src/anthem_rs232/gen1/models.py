"""Known Anthem Gen 1 receiver models."""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import DEFAULT_BAUD_RATE, Source

# Standard 18-input source map shared by D2/D2v/AVM 50v -- includes the
# letter-coded second-bank inputs (DVD 2-4, TV 2-4, SAT 2).
_FULL_SOURCE_MAP: dict[str, str] = {
    Source.CD.value: "CD",
    Source.STEREO.value: "STEREO",
    Source.SIX_CH.value: "6CH",
    Source.TAPE.value: "TAPE",
    Source.TUNER.value: "TUNER",
    Source.DVD_1.value: "DVD",
    Source.DVD_2.value: "DVD 2",
    Source.DVD_3.value: "DVD 3",
    Source.DVD_4.value: "DVD 4",
    Source.TV_1.value: "TV",
    Source.TV_2.value: "TV 2",
    Source.TV_3.value: "TV 3",
    Source.TV_4.value: "TV 4",
    Source.SAT_1.value: "SAT",
    Source.SAT_2.value: "SAT 2",
    Source.VCR.value: "VCR",
    Source.AUX.value: "AUX",
}

# Smaller source map for the AVM-2 / earlier MRX-class receivers (digits only).
_BASIC_SOURCE_MAP: dict[str, str] = {
    code: name
    for code, name in _FULL_SOURCE_MAP.items()
    if code.isdigit()
}


@dataclass(frozen=True)
class Gen1ReceiverModel:
    """Known capabilities of a Gen 1 Anthem receiver model."""

    name: str
    #: Default baud rate. The unit's setup menu can change this.
    baud_rate: int = DEFAULT_BAUD_RATE
    #: Number of zones (Main + Zone 2 + Rec). Set to 2 if no Rec zone.
    zones: int = 3
    #: True when a dedicated headphone path is exposed via the ``H?`` commands.
    has_headphone: bool = True
    #: True when an FM/AM tuner is present.
    has_tuner: bool = True
    #: True when Anthem Room Correction (ARC) is supported.
    arc: bool = False
    #: Source code map for this model (single-char code -> display name).
    source_map: dict[str, str] = field(default_factory=lambda: dict(_BASIC_SOURCE_MAP))


# -- Statement series ------------------------------------------------------

STATEMENT_D1 = Gen1ReceiverModel(
    name="Statement D1",
    baud_rate=9600,
    zones=3,
    has_headphone=True,
    has_tuner=True,
    arc=False,
    source_map=dict(_BASIC_SOURCE_MAP),
)

STATEMENT_D2 = Gen1ReceiverModel(
    name="Statement D2",
    baud_rate=19200,
    zones=3,
    has_headphone=True,
    has_tuner=True,
    arc=True,
    source_map=dict(_FULL_SOURCE_MAP),
)

STATEMENT_D2V = Gen1ReceiverModel(
    name="Statement D2v",
    baud_rate=19200,
    zones=3,
    has_headphone=True,
    has_tuner=True,
    arc=True,
    source_map=dict(_FULL_SOURCE_MAP),
)


# -- AVM series ------------------------------------------------------------

AVM_20 = Gen1ReceiverModel(
    name="AVM 20",
    baud_rate=9600,
    zones=3,
    source_map=dict(_BASIC_SOURCE_MAP),
)

AVM_30 = Gen1ReceiverModel(
    name="AVM 30",
    baud_rate=9600,
    zones=3,
    source_map=dict(_BASIC_SOURCE_MAP),
)

AVM_40 = Gen1ReceiverModel(
    name="AVM 40",
    baud_rate=9600,
    zones=3,
    source_map=dict(_BASIC_SOURCE_MAP),
)

AVM_50 = Gen1ReceiverModel(
    name="AVM 50",
    baud_rate=9600,
    zones=3,
    arc=True,
    source_map=dict(_FULL_SOURCE_MAP),
)

AVM_50V = Gen1ReceiverModel(
    name="AVM 50v",
    baud_rate=9600,
    zones=3,
    arc=True,
    source_map=dict(_FULL_SOURCE_MAP),
)


# -- MRX series (first generation) ----------------------------------------

MRX_300 = Gen1ReceiverModel(
    name="MRX 300",
    baud_rate=9600,
    zones=2,
    has_headphone=False,
    arc=True,
    source_map=dict(_BASIC_SOURCE_MAP),
)

MRX_500 = Gen1ReceiverModel(
    name="MRX 500",
    baud_rate=9600,
    zones=2,
    has_headphone=False,
    arc=True,
    source_map=dict(_BASIC_SOURCE_MAP),
)

MRX_700 = Gen1ReceiverModel(
    name="MRX 700",
    baud_rate=9600,
    zones=2,
    has_headphone=False,
    arc=True,
    source_map=dict(_BASIC_SOURCE_MAP),
)


# -- Generic fallback ------------------------------------------------------

OTHER = Gen1ReceiverModel(
    name="Other (Gen 1)",
    baud_rate=9600,
    zones=3,
    source_map=dict(_FULL_SOURCE_MAP),
)


#: All known Gen 1 receiver models, for iteration.
ALL_MODELS: tuple[Gen1ReceiverModel, ...] = (
    STATEMENT_D1,
    STATEMENT_D2,
    STATEMENT_D2V,
    AVM_20,
    AVM_30,
    AVM_40,
    AVM_50,
    AVM_50V,
    MRX_300,
    MRX_500,
    MRX_700,
)


#: Models keyed by identifier string.
MODELS: dict[str, Gen1ReceiverModel] = {
    "statement_d1": STATEMENT_D1,
    "statement_d2": STATEMENT_D2,
    "statement_d2v": STATEMENT_D2V,
    "avm_20": AVM_20,
    "avm_30": AVM_30,
    "avm_40": AVM_40,
    "avm_50": AVM_50,
    "avm_50v": AVM_50V,
    "mrx_300": MRX_300,
    "mrx_500": MRX_500,
    "mrx_700": MRX_700,
    "other": OTHER,
}
