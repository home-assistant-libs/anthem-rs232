"""Constants for the Anthem Gen 1 RS-232 protocol.

Gen 1 covers Statement D1/D2/D2v, AVM 20/30/40/50/50v, and MRX 300/500/700.
The wire format is line-feed terminated ASCII; commands and responses share
the same prefix grammar (``P{zone}{verb}{arg}``).
"""

from __future__ import annotations

from enum import Enum

# Per the AVM-2 spec, defaults vary by model. ``9600`` covers D1/AVM 50/MRX 300-700;
# the D2/D2v ship at ``19200``. Per-model overrides live on the ReceiverModel.
DEFAULT_BAUD_RATE = 9600
COMMAND_TIMEOUT = 2.0
DELAY_AFTER_POWER_ON = 12.0  # seconds before the unit accepts further commands
MIN_TIME_BETWEEN_COMMANDS = 0.250  # 250 ms throttle
MAX_LINE_LENGTH = 64  # bytes including the LF
TERMINATOR = b"\n"
COMMAND_SEPARATOR = b";"

# Volume bounds (dB). Gen 1 uses 0.5 dB steps for Main, 1.25 dB for Zone 2/HP.
MIN_MAIN_VOLUME_DB = -95.5
MAX_MAIN_VOLUME_DB = 10.0
MAIN_VOLUME_STEP = 0.5

MIN_ZONE2_VOLUME_DB = -70.0
MAX_ZONE2_VOLUME_DB = 10.0
ZONE2_VOLUME_STEP = 1.25

MIN_HEADPHONE_VOLUME_DB = -70.0
MAX_HEADPHONE_VOLUME_DB = 10.0
HEADPHONE_VOLUME_STEP = 1.25

# Channel trim bounds.
TRIM_MIN_DB = -10.0
TRIM_MAX_DB = 10.0
TRIM_STEP = 0.5

# Tone bounds.
TONE_MIN_DB = -12.0
TONE_MAX_DB = 12.0
TONE_STEP = 0.5

# Zone 2 / Headphone tone bounds (different scales).
ZONE2_TONE_MIN_DB = -14.0
ZONE2_TONE_MAX_DB = 14.0
ZONE2_TONE_STEP = 2.0

# FM/AM tuner bounds.
MIN_FM_FREQUENCY = 87.5
MAX_FM_FREQUENCY = 107.9
MIN_AM_FREQUENCY = 540
MAX_AM_FREQUENCY = 1710


class Zone(Enum):
    """Gen 1 zone identifiers."""

    MAIN = 1
    ZONE_2 = 2
    REC = 3  # "Zone 3" in the YAMLs; spec calls it "Rec" -- source-select only


class Source(Enum):
    """Gen 1 source codes (single ASCII character).

    The AVM-2 spec defines digits 0-9 plus letters d-j for additional disc/tv
    inputs that the D2/D2v expose. Source 0 is also the "Main follow" code on
    Zone 2 / Rec (i.e. ``P2S0`` = Zone 2 follows Main).
    """

    # Main zone codes
    CD = "0"  # spec calls it "direct" on the AVM-2; YAMLs label it CD
    STEREO = "1"
    SIX_CH = "2"
    TAPE = "3"
    TUNER = "4"
    DVD_1 = "5"
    DVD_2 = "d"
    DVD_3 = "e"
    DVD_4 = "f"
    TV_1 = "6"
    TV_2 = "g"
    TV_3 = "h"
    TV_4 = "i"
    SAT_1 = "7"
    SAT_2 = "j"
    VCR = "8"
    AUX = "9"


#: Source code used by Zone 2 / Rec to mean "follow the Main zone".
ZONE_FOLLOW_MAIN = "0"


class DecoderMode(Enum):
    """Decoder modes (P1D)."""

    AC3 = 0
    DTS = 1
    MPEG = 2
    STEREO = 3
    PRO_LOGIC = 4
    DIRECT = 5


class EffectMode(Enum):
    """Surround effect modes (P1E)."""

    OFF = 0
    PRO_LOGIC = 1
    HALL = 2
    THEATER = 3
    STADIUM = 4
    CLUB = 5
    CHURCH = 6
    FIVE_CH_STEREO = 7
    FIVE_CH_MONO = 8
    NINETY_SIX_KHZ_STEREO = 9


class DolbyDynamicRange(Enum):
    """Dolby Digital dynamic range compression (P1C)."""

    NORMAL = 0
    REDUCED = 1
    LATE_NIGHT = 2


class SleepTimer(Enum):
    """Main zone sleep timer (P1Z)."""

    OFF = 0
    THIRTY_MIN = 1
    SIXTY_MIN = 2
    NINETY_MIN = 3


class TunerMode(Enum):
    """FM tuner mode (TH)."""

    AUTO = 0
    MONO = 1


class TunerBand(Enum):
    """Currently active tuner band (derived from TT? response prefix)."""

    AM = "AM"
    FM = "FM"


class FrontPanelLock(Enum):
    """Front panel lock (FPL)."""

    UNLOCKED = 0
    LOCKED = 1


# -- Error response strings --------------------------------------------------
# The AVM-2 spec defines verbose ASCII error replies. These are the canonical
# substrings to match against a received line.
ERR_PARAMETER_OUT_OF_RANGE = "Parameter Out-of-range"
ERR_INVALID_COMMAND = "Invalid Command"
ERR_MAIN_OFF = "Main Off"
ERR_ZONE2_OFF = "Zone2 Off"
ERR_UNIT_OFF = "Unit Off"
ERR_ALREADY_IN_USE = "Already in use"

#: All known Gen 1 error phrases. Used by the dispatcher to recognize errors.
ERROR_PHRASES = (
    ERR_PARAMETER_OUT_OF_RANGE,
    ERR_INVALID_COMMAND,
    ERR_MAIN_OFF,
    ERR_ZONE2_OFF,
    ERR_UNIT_OFF,
    ERR_ALREADY_IN_USE,
)
