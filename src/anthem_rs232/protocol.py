"""Protocol helpers for anthem_rs232."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from .const import ErrorKind

#: Z1VOLsyy / Z2VOLsyy where s is +/- and yy is 1-3 digits.
_VOLUME_RE = re.compile(r"^([+-])(\d{1,3})$")
#: Z1LEVyszz where y is 0-7 and szz is +/- + 1-2 digits.
_LEVEL_RE = re.compile(r"^(\d)([+-])(\d{1,2})$")
#: Z1TONyszz where y is 0-1 and szz is +/- + 1-2 digits.
_TONE_RE = re.compile(r"^([01])([+-])(\d{1,2})$")


def parse_volume_param(param: str) -> float:
    """Convert a Z?VOL parameter (e.g. ``-35``, ``+5``) to a dB value."""
    match = _VOLUME_RE.match(param)
    if match is None:
        raise ValueError(f"Invalid volume parameter: {param!r}")
    sign, value = match.groups()
    db = float(value)
    return -db if sign == "-" else db


def volume_to_param(db: float) -> str:
    """Convert a dB value to a Z?VOLsyy parameter."""
    rounded = int(round(db))
    sign = "-" if rounded < 0 else "+"
    return f"{sign}{abs(rounded):02d}"


def parse_level_param(param: str) -> tuple[int, float]:
    """Parse a Z1LEVyszz parameter into (channel index, dB)."""
    match = _LEVEL_RE.match(param)
    if match is None:
        raise ValueError(f"Invalid level parameter: {param!r}")
    channel, sign, value = match.groups()
    db = float(value)
    return int(channel), (-db if sign == "-" else db)


def level_to_param(channel: int, db: float) -> str:
    """Format a Z1LEVyszz parameter from channel index + dB."""
    rounded = int(round(db))
    sign = "-" if rounded < 0 else "+"
    return f"{channel}{sign}{abs(rounded):02d}"


def parse_tone_param(param: str) -> tuple[int, float]:
    """Parse a Z1TONyszz parameter into (axis, dB) where axis is 0=bass / 1=treble."""
    match = _TONE_RE.match(param)
    if match is None:
        raise ValueError(f"Invalid tone parameter: {param!r}")
    axis, sign, value = match.groups()
    db = float(value)
    return int(axis), (-db if sign == "-" else db)


def tone_to_param(axis: int, db: float) -> str:
    """Format a Z1TONyszz parameter from axis (0/1) + dB."""
    rounded = int(round(db))
    sign = "-" if rounded < 0 else "+"
    return f"{axis}{sign}{abs(rounded):02d}"


def parse_balance_param(param: str) -> int:
    """Parse a Z1BALyyy parameter (0-100, 50 = center)."""
    return int(param)


def balance_to_param(percent: int) -> str:
    """Format a Z1BALyyy parameter (0-100)."""
    if not 0 <= percent <= 100:
        raise ValueError(f"Balance percent out of range: {percent}")
    return f"{percent:03d}"


def parse_fm_frequency(param: str) -> float:
    """Parse a T1FMS frequency parameter into MHz."""
    return float(param)


def fm_frequency_to_param(mhz: float) -> str:
    """Format a T1FMS frequency parameter (xxx.xx)."""
    return f"{mhz:0.2f}"


@dataclass
class ErrorReply:
    """An error response from the receiver (``!E/R/I/Z<original>``)."""

    kind: ErrorKind
    original: str


def parse_error_reply(line: str) -> ErrorReply | None:
    """Parse an Anthem error reply, or return ``None`` if not an error."""
    if not line.startswith("!") or len(line) < 2:
        return None
    try:
        kind = ErrorKind(line[1])
    except ValueError:
        return None
    return ErrorReply(kind=kind, original=line[2:])


@dataclass
class PendingQuery:
    """A pending query waiting for a response or error."""

    prefix: str
    future: asyncio.Future[str]
