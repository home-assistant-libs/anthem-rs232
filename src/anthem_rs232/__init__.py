"""Async library for the Anthem RS-232 protocol family.

Top-level exports cover the **Gen 2** protocol (MRX 310-1120, AVM 60). Gen 1
support (Statement D1/D2/D2v, AVM 20-50, MRX 300-700) lives in the
``anthem_rs232.gen1`` subpackage; ``Gen1Receiver`` is also re-exported here
for convenience.
"""

from . import gen1
from .const import (
    BAUD_RATE,
    COMMAND_TIMEOUT,
    MAX_FM_FREQUENCY,
    MAX_INPUTS,
    MAX_PRESET,
    MAX_VOLUME_DB,
    MIN_FM_FREQUENCY,
    MIN_PRESET,
    MIN_VOLUME_DB,
    PROBE_TIMEOUT,
    TERMINATOR,
    AudioInputChannels,
    AudioInputFormat,
    AudioListeningMode,
    Channel,
    DolbyDynamicRange,
    ErrorKind,
    FrontPanelBrightness,
    ToneControl,
    TunerStatus,
    VideoInputResolution,
    Zone,
)
from .players import AnthemPlayer, MainPlayer, ZonePlayer
from .protocol import (
    ErrorReply,
    balance_to_param as _balance_to_param,
    fm_frequency_to_param as _fm_frequency_to_param,
    level_to_param as _level_to_param,
    parse_balance_param as _parse_balance_param,
    parse_error_reply as _parse_error_reply,
    parse_fm_frequency as _parse_fm_frequency,
    parse_level_param as _parse_level_param,
    parse_tone_param as _parse_tone_param,
    parse_volume_param as _parse_volume_param,
    tone_to_param as _tone_to_param,
    volume_to_param as _volume_to_param,
)
from .gen1 import Gen1CommandError, Gen1Receiver
from .probe import ProbeResult, probe
from .receiver import AnthemReceiver, CommandError, StateCallback
from .state import (
    InputConfig,
    MainZoneState,
    ReceiverState,
    TriggerState,
    ZoneState,
)

__all__ = [
    "AnthemPlayer",
    "AnthemReceiver",
    "Gen1CommandError",
    "Gen1Receiver",
    "ProbeResult",
    "gen1",
    "probe",
    "AudioInputChannels",
    "AudioInputFormat",
    "AudioListeningMode",
    "BAUD_RATE",
    "COMMAND_TIMEOUT",
    "Channel",
    "CommandError",
    "DolbyDynamicRange",
    "ErrorKind",
    "ErrorReply",
    "FrontPanelBrightness",
    "InputConfig",
    "MAX_FM_FREQUENCY",
    "MAX_INPUTS",
    "MAX_PRESET",
    "MAX_VOLUME_DB",
    "MIN_FM_FREQUENCY",
    "MIN_PRESET",
    "MIN_VOLUME_DB",
    "MainPlayer",
    "MainZoneState",
    "PROBE_TIMEOUT",
    "ReceiverState",
    "StateCallback",
    "TERMINATOR",
    "ToneControl",
    "TriggerState",
    "TunerStatus",
    "VideoInputResolution",
    "Zone",
    "ZonePlayer",
    "ZoneState",
    "_balance_to_param",
    "_fm_frequency_to_param",
    "_level_to_param",
    "_parse_balance_param",
    "_parse_error_reply",
    "_parse_fm_frequency",
    "_parse_level_param",
    "_parse_tone_param",
    "_parse_volume_param",
    "_tone_to_param",
    "_volume_to_param",
]
