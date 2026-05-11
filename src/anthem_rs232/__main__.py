"""CLI to test an Anthem MRX 1120 / 720 / 520 / AVM 60 over RS232.

Usage:
    python -m anthem_rs232 /dev/ttyUSB0
    python -m anthem_rs232 /dev/ttyUSB0 --probe
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import AnthemReceiver, ReceiverState


def _format_db(db: float | None) -> str:
    if db is None:
        return "?"
    if db >= 0:
        return f"+{db:.1f} dB"
    return f"{db:.1f} dB"


def _format_enum(val: object | None) -> str:
    if val is None:
        return "?"
    if hasattr(val, "name"):
        return val.name
    return str(val)


def _print_state(state: ReceiverState) -> None:
    print()
    print("=== Receiver Status ===")
    print()

    print(f"  Model:           {state.model or '?'}")
    print(f"  Software:        {state.software_version or '?'}")
    print(f"  Region:          {state.region or '?'}")
    print(f"  MAC:             {state.mac_address or '?'}")
    print(
        f"  System power:    "
        f"{'ON' if state.power else 'STANDBY' if state.power is not None else '?'}"
    )
    print(f"  Front panel:     {_format_enum(state.front_panel_brightness)}")
    print(f"  Standby IP:      {state.standby_ip_control}")
    print(f"  Echo (reports):  {state.echo_enabled}")

    if state.inputs:
        print()
        print(f"  Inputs ({len(state.inputs)}):")
        for idx in sorted(state.inputs):
            cfg = state.inputs[idx]
            short = cfg.short_name or "?"
            long_ = f" ({cfg.long_name})" if cfg.long_name else ""
            print(f"    {idx:>2d}: {short}{long_}")

    mz = state.main_zone
    print()
    print("  Main zone (Z1):")
    print(
        f"    Power:         "
        f"{'ON' if mz.power else 'OFF' if mz.power is not None else '?'}"
    )
    print(f"    Input:         {mz.input_index if mz.input_index is not None else '?'}")
    print(f"    Volume:        {_format_db(mz.volume)}")
    print(
        f"    Mute:          "
        f"{'ON' if mz.mute else 'OFF' if mz.mute is not None else '?'}"
    )
    print(f"    ARC:           {mz.arc_enabled}")
    print(f"    Balance:       {mz.balance if mz.balance is not None else '?'}")
    print(f"    Listening:     {_format_enum(mz.audio_listening_mode)}")
    print(f"    Audio in:      {mz.audio_input_name or '?'} ({_format_enum(mz.audio_input_format)})")
    print(f"    Audio chans:   {_format_enum(mz.audio_input_channels)}")
    print(f"    Video res:     {_format_enum(mz.video_input_resolution)}")
    print(f"    Bass / Treble: {_format_db(mz.bass)} / {_format_db(mz.treble)}")
    if mz.tuner_frequency is not None:
        print(f"    FM:            {mz.tuner_frequency:0.2f} MHz (preset {mz.tuner_preset or '-'})")
    if mz.channel_levels:
        print()
        print("    Channel levels:")
        for ch, db in sorted(mz.channel_levels.items()):
            print(f"      ch {ch}: {_format_db(db)}")

    z2 = state.zone_2
    if z2.power is not None or z2.input_index is not None or z2.volume is not None:
        print()
        print("  Zone 2:")
        print(
            f"    Power:         "
            f"{'ON' if z2.power else 'OFF' if z2.power is not None else '?'}"
        )
        if z2.input_index is not None:
            print(f"    Input:         {z2.input_index}")
        if z2.volume is not None:
            print(f"    Volume:        {_format_db(z2.volume)}")
        if z2.mute is not None:
            print(f"    Mute:          {'ON' if z2.mute else 'OFF'}")

    print()


async def _run(port: str, probe: bool) -> None:
    receiver = AnthemReceiver(port)

    print(f"Connecting to {port}...")
    try:
        await receiver.connect()
        print("Querying receiver state...")
        await receiver.query_state()
    except ConnectionError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    try:
        _print_state(receiver.state)

        if probe:
            print("Probing inputs...")
            inputs = await receiver.probe_inputs()
            print()
            print(f"Configured inputs ({len(inputs)}):")
            for idx in sorted(inputs):
                cfg = inputs[idx]
                short = cfg.short_name or "?"
                long_ = f" ({cfg.long_name})" if cfg.long_name else ""
                print(f"  {idx:>2d}: {short}{long_}")
            print()
    finally:
        await receiver.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test an Anthem MRX 1120 / 720 / 520 / AVM 60 over RS232",
    )
    parser.add_argument("port", help="Serial port (e.g. /dev/ttyUSB0)")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Probe configured inputs",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.port, args.probe))


if __name__ == "__main__":
    main()
