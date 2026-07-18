"""Constants and enums shared across the anthem_rs232 package."""

from enum import Enum

# Anthem MRX x20 / AVM 60 serial defaults: 115200 8N1, semicolon terminator.
BAUD_RATE = 115200
COMMAND_TIMEOUT = 2.0  # seconds to wait for a response
WATCHDOG_INTERVAL = 60.0  # seconds without RX before probing the link
# ECO standby consumes the first frame as MCU wake-up (spec notes 10/11),
# so probe several times before declaring the link dead.
WATCHDOG_PROBE_ATTEMPTS = 3
PROBE_TIMEOUT = 0.8  # seconds to wait for each probe attempt
TERMINATOR = b";"

# Maximum number of input configurations the receiver can expose.
MAX_INPUTS = 30

# Tuner preset range.
MIN_PRESET = 1
MAX_PRESET = 30

# FM frequency range (MHz).
MIN_FM_FREQUENCY = 87.50
MAX_FM_FREQUENCY = 108.00

# Volume range bounds for the MRX 1120 / 720 / 520. The receiver clamps to
# its actual range and the spec says "Entry is rounded to nearest valid value",
# so these are upper/lower bounds rather than enforced limits.
MIN_VOLUME_DB = -90.0
MAX_VOLUME_DB = 10.0

# Per-input lip sync delay (SLIP), in milliseconds.
MIN_LIP_SYNC_MS = 0
MAX_LIP_SYNC_MS = 150
LIP_SYNC_STEP_MS = 5

# Per-input Dolby Volume Leveler (SDVL). 0 = off.
MIN_DOLBY_VOLUME_LEVELER = 0
MAX_DOLBY_VOLUME_LEVELER = 9

# All command/response prefixes that come from the receiver. Sorted by
# length descending so longer matches win (e.g. ``Z1IRH`` before ``Z1IR``).
_RESPONSE_PREFIXES: tuple[str, ...] = (
    "IDQ",
    "IDM",
    "IDS",
    "IDR",
    "IDB",
    "IDH",
    "IDN",
    "ECH",
    "FPB",
    "SDVS",
    "SDVL",
    "SLIP",
    "SIP",
    "SSP",
    "SPN",
    "ICN",
    "ISN",
    "ILN",
    "Z1POW",
    "Z2POW",
    "Z3POW",
    "Z0POW",
    "Z1INP",
    "Z2INP",
    "Z1VOL",
    "Z2VOL",
    "Z1MUT",
    "Z2MUT",
    "Z1ARC",
    "Z2ARC",
    "Z1BAL",
    "Z1LEV",
    "Z1TON",
    "Z1ALM",
    "Z1WST",
    "Z1DST",
    "Z1PST",
    "Z1DYN",
    "Z1DIA",
    "Z1SMD",
    "Z1VIR",
    "Z1IRH",
    "Z1IRV",
    "Z1AIC",
    "Z1AIF",
    "Z1BRT",
    "Z1SRT",
    "Z1AIN",
    "Z1AIR",
    "Z1TBS",
    "Z2TBS",
    "T1FMS",
    "T1PSA",
    "R0CTL",
    "R1CTL",
    "R0SET",
    "R1SET",
)


class ErrorKind(Enum):
    """Anthem error reply categories. The receiver echoes the original command."""

    EXECUTION = "E"  # !E -- recognized but cannot execute
    OUT_OF_RANGE = "R"  # !R -- parameter out of range
    INVALID = "I"  # !I -- invalid command
    ZONE_OFF = "Z"  # !Z -- zone is off (system not in standby)


class FrontPanelBrightness(Enum):
    """Front panel display brightness."""

    OFF = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class AudioListeningMode(Enum):
    """Audio Listening Mode (Z1ALM)."""

    NONE = 0
    ANTHEM_LOGIC_MOVIE = 1
    ANTHEM_LOGIC_MUSIC = 2
    PLIIX_MOVIE = 3
    PLIIX_MUSIC = 4
    NEO6_CINEMA = 5
    NEO6_MUSIC = 6
    ALL_CHANNEL_STEREO = 7
    ALL_CHANNEL_MONO = 8
    MONO = 9
    MONO_ACADEMY = 10
    MONO_LEFT = 11
    MONO_RIGHT = 12
    HIGH_BLEND = 13
    DOLBY_SURROUND = 14
    NEOX_CINEMA = 15
    NEOX_MUSIC = 16


class AudioInputChannels(Enum):
    """Detected audio input channel layout (Z1AIC)."""

    NO_INPUT = 0
    OTHER = 1
    MONO = 2
    TWO_CHANNEL = 3
    FIVE_ONE = 4
    SIX_ONE = 5
    SEVEN_ONE = 6
    ATMOS = 7


class AudioInputFormat(Enum):
    """Detected audio input format (Z1AIF)."""

    NO_INPUT = 0
    ANALOG = 1
    PCM = 2
    DOLBY = 3
    DSD = 4
    DTS = 5
    ATMOS = 6


class VideoInputResolution(Enum):
    """Detected video input resolution (Z1VIR)."""

    NO_INPUT = 0
    OTHER = 1
    P1080_60 = 2
    P1080_50 = 3
    P1080_24 = 4
    I1080_60 = 5
    I1080_50 = 6
    P720_60 = 7
    P720_50 = 8
    P576_50 = 9
    I576_50 = 10
    P480_60 = 11
    I480_60 = 12
    THREE_D = 13
    FOUR_K = 14


class DolbyDynamicRange(Enum):
    """Dolby Digital dynamic range setting (Z1DYN)."""

    NORMAL = 0
    REDUCED = 1
    LATE_NIGHT = 2


class TunerStatus(Enum):
    """Tuner status (ZxTBS)."""

    OFF = 0
    FM = 1


class Channel(Enum):
    """Channel groups for Z1LEV (level) commands."""

    SUBS = 0
    FRONTS = 1
    CENTER = 2
    SURROUNDS = 3
    BACKS = 4
    LFE = 5
    HEIGHTS_1 = 6
    HEIGHTS_2 = 7


class ToneControl(Enum):
    """Z1TON tone control axis."""

    BASS = 0
    TREBLE = 1


class Zone(Enum):
    """Anthem zone identifiers."""

    ALL = 0  # only valid for the power command
    MAIN = 1
    ZONE_2 = 2
    ZONE_3 = 3  # not present on MRX 1120 / 720 / 520
