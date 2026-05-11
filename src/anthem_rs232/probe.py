"""Detect the connected Anthem receiver model and protocol generation.

The probe walks the three configurations Anthem ships:

1. Gen 2 @ 115200 baud, ``;``-terminated -- MRX 310/510/710/520/720/1120, AVM 60.
2. Gen 1 @ 9600 baud, ``\\n``-terminated -- Statement D1, AVM 20-50, MRX 300/500/700.
3. Gen 1 @ 19200 baud, ``\\n``-terminated -- Statement D2, D2v.

Each step opens the port at the candidate baud rate, sends the protocol's
identify query, and waits briefly for a recognisable reply. The first match
wins; if nothing answers, the function returns ``None``.

Usage:

    from anthem_rs232.probe import probe
    result = await probe("/dev/ttyUSB0")
    if result is None:
        print("No Anthem found")
    else:
        print(f"{result.model_name} (Gen {result.generation}, {result.baud_rate} baud)")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import serialx

from . import models as gen2_models
from .gen1 import models as gen1_models

_LOGGER = logging.getLogger(__name__)

#: Default per-attempt timeout. The Gen 2 spec promises < 100 ms response;
#: Gen 1 is similar. 0.8 s is plenty plus headroom for slow proxies.
DEFAULT_TIMEOUT = 0.8

#: Default baud rates to try, in order.
DEFAULT_BAUD_ATTEMPTS: tuple[tuple[int, int], ...] = (
    # (generation, baud)
    (2, 115200),  # Gen 2: MRX 310-1120, AVM 60
    (1, 9600),    # Gen 1: D1, AVM 20-50, MRX 300/500/700
    (1, 19200),   # Gen 1: Statement D2, D2v
)


@dataclass
class ProbeResult:
    """Outcome of a successful probe."""

    #: Detected protocol generation (1 or 2).
    generation: int
    #: Model name as reported by the receiver (e.g. ``"MRX 1120"``).
    model_name: str
    #: Baud rate the receiver answered at.
    baud_rate: int
    #: Raw identify line from the receiver (without terminators).
    raw_response: str
    #: Matching ``ReceiverModel`` constant from this library, or ``None`` if
    #: the model name didn't match a known definition.
    model: object | None = None


def _lookup_model(generation: int, model_name: str) -> object | None:
    """Look up the matching model constant for the detected name."""
    target = model_name.strip().upper()
    if generation == 2:
        for m in gen2_models.ALL_MODELS:
            if m.name.upper() == target:
                return m
    elif generation == 1:
        for m in gen1_models.ALL_MODELS:
            if m.name.upper() == target:
                return m
    return None


async def _try_gen2(
    port: str, baud: int, timeout: float
) -> ProbeResult | None:
    """Probe for a Gen 2 receiver. Returns None if no recognisable response."""
    try:
        reader, writer = await serialx.open_serial_connection(port, baudrate=baud)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Gen 2 probe @ %d: open failed: %s", baud, exc)
        return None

    try:
        # Try IDM? twice (some MRX firmwares drop the first frame after open).
        for attempt in range(2):
            writer.write(b"IDM?;")
            await writer.drain()
            line = await _read_terminated(reader, b";", timeout)
            if line is None:
                continue
            text = line.decode("ascii", errors="replace").strip()
            _LOGGER.debug("Gen 2 IDM (attempt %d) -> %r", attempt + 1, text)
            if text.startswith("IDM"):
                model_name = text.removeprefix("IDM").strip()
                return ProbeResult(
                    generation=2,
                    model_name=model_name,
                    baud_rate=baud,
                    raw_response=text,
                    model=_lookup_model(2, model_name),
                )

        # Some MRX 1120 firmwares silently drop IDM? when in standby. Z1POW?
        # always answers, so fall back to it as a Gen 2 confirmation.
        writer.write(b"Z1POW?;")
        await writer.drain()
        line = await _read_terminated(reader, b";", timeout)
        if line is None:
            return None
        text = line.decode("ascii", errors="replace").strip()
        _LOGGER.debug("Gen 2 Z1POW -> %r", text)
        if text.startswith("Z1POW"):
            return ProbeResult(
                generation=2,
                model_name="Unknown Gen 2 (powered down -- run again with main on for IDM)",
                baud_rate=baud,
                raw_response=text,
                model=None,
            )
        return None
    finally:
        writer.close()
        await writer.wait_closed()


async def _try_gen1(
    port: str, baud: int, timeout: float
) -> ProbeResult | None:
    """Probe for a Gen 1 receiver. Returns None if no recognisable response."""
    try:
        reader, writer = await serialx.open_serial_connection(port, baudrate=baud)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Gen 1 probe @ %d: open failed: %s", baud, exc)
        return None

    try:
        writer.write(b"?\n")
        await writer.drain()
        line = await _read_terminated(reader, b"\n", timeout)
        if line is None:
            return None
        text = line.decode("ascii", errors="replace").strip("\r\n ")
        _LOGGER.debug("Gen 1 ? -> %r", text)
        if not (text.startswith("(") and text.endswith(")")):
            return None
        info = text[1:-1]
        parts = [p.strip() for p in info.split(",")]
        if not parts:
            return None
        model_name = parts[0]
        return ProbeResult(
            generation=1,
            model_name=model_name,
            baud_rate=baud,
            raw_response=info,
            model=_lookup_model(1, model_name),
        )
    finally:
        writer.close()
        await writer.wait_closed()


async def _read_terminated(
    reader: asyncio.StreamReader, terminator: bytes, timeout: float
) -> bytes | None:
    """Read one terminated frame within ``timeout`` seconds, or return None."""
    try:
        data = await asyncio.wait_for(reader.readuntil(terminator), timeout=timeout)
    except (TimeoutError, asyncio.IncompleteReadError):
        return None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("read_terminated error: %s", exc)
        return None
    return data.rstrip(terminator)


async def probe(
    port: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    attempts: tuple[tuple[int, int], ...] = DEFAULT_BAUD_ATTEMPTS,
) -> ProbeResult | None:
    """Detect the connected Anthem receiver model and protocol generation.

    Walks the candidate (generation, baud) pairs in ``attempts`` order and
    returns the first ``ProbeResult`` that matches. Returns ``None`` if no
    Anthem receiver answered at any of the candidate configurations.

    The default ``attempts`` covers Gen 2 (115200) and Gen 1 (9600 + 19200);
    pass a custom tuple to narrow or reorder the search.
    """
    for generation, baud in attempts:
        if generation == 2:
            result = await _try_gen2(port, baud, timeout)
        elif generation == 1:
            result = await _try_gen1(port, baud, timeout)
        else:
            raise ValueError(f"Unknown generation: {generation}")
        if result is not None:
            return result
    return None


# -- CLI ---------------------------------------------------------------------


def _constant_name(model: object) -> str:
    """Look up the module-level name a model dataclass was bound to."""
    for module in (gen2_models, gen1_models):
        for name, value in vars(module).items():
            if value is model and name.isupper():
                return name
    return "?"


async def _cli_run(port: str, timeout: float) -> int:
    print(f"Probing {port}...", flush=True)
    result = await probe(port, timeout=timeout)
    if result is None:
        print("\nNo Anthem receiver responded.")
        print("\nTried:")
        print("  Gen 2 @ 115200 baud (IDM?; / Z1POW?;)")
        print("  Gen 1 @  9600 baud (?\\n)")
        print("  Gen 1 @ 19200 baud (?\\n)")
        return 1

    print()
    print("=== Detected ===")
    print(f"  Model:      {result.model_name}")
    print(f"  Generation: Gen {result.generation}")
    print(f"  Baud rate:  {result.baud_rate}")
    print(f"  Raw reply:  {result.raw_response!r}")
    if result.model is not None:
        const = _constant_name(result.model)
        if result.generation == 2:
            print(f"  Constant:   anthem_rs232.models.{const}")
        else:
            print(f"  Constant:   anthem_rs232.gen1.{const}")
    else:
        print("  Constant:   (unknown -- model name didn't match a library definition)")
    return 0


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Detect an Anthem receiver model and protocol generation",
    )
    parser.add_argument(
        "port",
        help="Serial port (e.g. /dev/ttyUSB0) or serialx URL (e.g. esphome://...)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Per-attempt timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_cli_run(args.port, args.timeout)))


if __name__ == "__main__":
    main()
