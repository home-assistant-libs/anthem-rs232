"""Protocol parsers and encoders for the Anthem Gen 1 RS-232 protocol."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from .const import ERROR_PHRASES

# -- Volume / level encoding -------------------------------------------------

#: Matches signed dB values like ``-30.5``, ``0.0``, ``+5``. Anthem accepts
#: both ``sxx.x`` and ``sxx.xx`` and integer forms; we always emit one decimal.
_DB_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def parse_db(value: str) -> float:
    """Parse a Gen 1 dB value (``"-30.5"``, ``"+5.0"``, ``"0"``) to a float."""
    if not _DB_RE.match(value):
        raise ValueError(f"Invalid dB value: {value!r}")
    return float(value)


def db_to_param(db: float, *, step: float = 0.5) -> str:
    """Format a dB value for the wire, snapped to ``step`` and 1 decimal place.

    Anthem accepts both ``sxx.x`` and an explicit ``+`` for positive numbers;
    the front panel and the spec examples use a leading sign only on negatives,
    so that's what we emit.
    """
    snapped = round(db / step) * step
    return f"{snapped:.1f}"


# -- Zone status responses ---------------------------------------------------

# Main zone (P1?): P1S{u}V{v}M{w}D{x}E{y}    -- D and E are optional in some firmwares.
_MAIN_STATUS_RE = re.compile(
    r"^P1S(?P<source>[0-9a-z])V(?P<volume>[+-]?\d+(?:\.\d+)?)"
    r"M(?P<mute>[01])"
    r"(?:D(?P<decoder>\d+))?"
    r"(?:E(?P<effect>\d+))?$"
)

# Zone 2 (P2?): P2S{u}V{v}M{w}
_ZONE2_STATUS_RE = re.compile(
    r"^P2S(?P<source>[0-9a-z])V(?P<volume>[+-]?\d+(?:\.\d+)?)M(?P<mute>[01])$"
)

# Rec / Zone 3 (P3?): P3S{u}  -- source-only.
_REC_STATUS_RE = re.compile(r"^P3S(?P<source>[0-9a-z])$")

# Headphone (H?): HS{u}V{v}M{w}
_HEADPHONE_STATUS_RE = re.compile(
    r"^HS(?P<source>[0-9a-z])V(?P<volume>[+-]?\d+(?:\.\d+)?)M(?P<mute>[01])$"
)

# Single-field responses.
_POWER_RE = re.compile(r"^P(?P<zone>[1-3])P(?P<state>[01])$")
_VOLUME_RE = re.compile(
    r"^P(?P<zone>[1-3])V(?:M)?(?P<volume>[+-]?\d+(?:\.\d+)?)$"
)
_MUTE_RE = re.compile(r"^P(?P<zone>[1-3])M(?P<state>[01])$")
_SOURCE_RE = re.compile(r"^P(?P<zone>[1-3])S(?P<source>[0-9a-z])$")
_DECODER_RE = re.compile(r"^P1D(?P<source>\d)(?P<mode>\d)$")
_EFFECT_RE = re.compile(r"^P1E(?P<source>\d)(?P<mode>\d)$")
_FM_TUNER_RE = re.compile(r"^TFT(?P<frequency>\d+(?:\.\d+)?)$")
_AM_TUNER_RE = re.compile(r"^TAT(?P<frequency>\d+)$")
_TRIGGER_RE = re.compile(r"^t(?P<trigger>[1-3])T(?P<state>[01])$")
_HEADPHONE_VOL_RE = re.compile(r"^HV(?P<volume>[+-]?\d+(?:\.\d+)?)$")
_HEADPHONE_MUTE_RE = re.compile(r"^HM(?P<state>[01])$")
_VERSION_RE = re.compile(r"^\((?P<info>[^)]+)\)$")


@dataclass
class MainZoneStatus:
    """Decoded main zone status (P1?)."""

    source: str
    volume: float
    mute: bool
    decoder: int | None = None
    effect: int | None = None


@dataclass
class ZoneStatus:
    """Decoded Zone 2 status (P2?)."""

    source: str
    volume: float
    mute: bool


@dataclass
class HeadphoneStatus:
    """Decoded headphone status (H?)."""

    source: str
    volume: float
    mute: bool


def parse_main_status(payload: str) -> MainZoneStatus | None:
    m = _MAIN_STATUS_RE.match(payload)
    if m is None:
        return None
    return MainZoneStatus(
        source=m["source"],
        volume=float(m["volume"]),
        mute=m["mute"] == "1",
        decoder=int(m["decoder"]) if m["decoder"] is not None else None,
        effect=int(m["effect"]) if m["effect"] is not None else None,
    )


def parse_zone2_status(payload: str) -> ZoneStatus | None:
    m = _ZONE2_STATUS_RE.match(payload)
    if m is None:
        return None
    return ZoneStatus(
        source=m["source"],
        volume=float(m["volume"]),
        mute=m["mute"] == "1",
    )


def parse_rec_source(payload: str) -> str | None:
    m = _REC_STATUS_RE.match(payload)
    return m["source"] if m else None


def parse_headphone_status(payload: str) -> HeadphoneStatus | None:
    m = _HEADPHONE_STATUS_RE.match(payload)
    if m is None:
        return None
    return HeadphoneStatus(
        source=m["source"],
        volume=float(m["volume"]),
        mute=m["mute"] == "1",
    )


# -- Per-field response parsing ----------------------------------------------


@dataclass
class ZoneField:
    """A simple per-zone field response (power, volume, mute, source)."""

    zone: int
    value: object


def parse_power(payload: str) -> ZoneField | None:
    m = _POWER_RE.match(payload)
    return ZoneField(int(m["zone"]), m["state"] == "1") if m else None


def parse_volume(payload: str) -> ZoneField | None:
    m = _VOLUME_RE.match(payload)
    return ZoneField(int(m["zone"]), float(m["volume"])) if m else None


def parse_mute(payload: str) -> ZoneField | None:
    m = _MUTE_RE.match(payload)
    return ZoneField(int(m["zone"]), m["state"] == "1") if m else None


def parse_source(payload: str) -> ZoneField | None:
    m = _SOURCE_RE.match(payload)
    return ZoneField(int(m["zone"]), m["source"]) if m else None


def parse_decoder(payload: str) -> tuple[int, int] | None:
    """Returns (source_index, decoder_mode_int) or None."""
    m = _DECODER_RE.match(payload)
    return (int(m["source"]), int(m["mode"])) if m else None


def parse_effect(payload: str) -> tuple[int, int] | None:
    """Returns (source_index, effect_mode_int) or None."""
    m = _EFFECT_RE.match(payload)
    return (int(m["source"]), int(m["mode"])) if m else None


def parse_fm_frequency(payload: str) -> float | None:
    m = _FM_TUNER_RE.match(payload)
    return float(m["frequency"]) if m else None


def parse_am_frequency(payload: str) -> int | None:
    m = _AM_TUNER_RE.match(payload)
    return int(m["frequency"]) if m else None


def parse_headphone_volume(payload: str) -> float | None:
    m = _HEADPHONE_VOL_RE.match(payload)
    return float(m["volume"]) if m else None


def parse_headphone_mute(payload: str) -> bool | None:
    m = _HEADPHONE_MUTE_RE.match(payload)
    return m["state"] == "1" if m else None


def parse_trigger(payload: str) -> tuple[int, bool] | None:
    """Returns (trigger_number, on_state) or None."""
    m = _TRIGGER_RE.match(payload)
    return (int(m["trigger"]), m["state"] == "1") if m else None


def parse_version(payload: str) -> str | None:
    """Parse the identify response: ``(AVM 2,Version 1.00,Jun 26 2000)``."""
    m = _VERSION_RE.match(payload)
    return m["info"] if m else None


# -- Error matching ----------------------------------------------------------


def match_error(payload: str) -> str | None:
    """Return the error phrase if ``payload`` is one of the known Gen 1 errors."""
    for phrase in ERROR_PHRASES:
        if phrase in payload:
            return phrase
    return None


# -- Pending query ----------------------------------------------------------


@dataclass
class PendingQuery:
    """A pending query waiting for its response."""

    matcher: object  # callable returning a non-None decoded value, or None
    future: asyncio.Future


# -- Helpers ----------------------------------------------------------------


def split_lines(buf: bytes) -> tuple[list[bytes], bytes]:
    """Split a buffer on LF and on the in-line ``;`` separator.

    Returns ``(complete_messages, residual_buffer)``. The residual is whatever
    didn't end with a delimiter and should be carried over to the next read.
    """
    if b"\n" not in buf:
        return [], buf
    parts = buf.split(b"\n")
    residual = parts[-1]
    out: list[bytes] = []
    for line in parts[:-1]:
        # Multiple commands on one line are ``;``-separated.
        for piece in line.split(b";"):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out, residual
