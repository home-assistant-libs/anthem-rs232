"""CLI to test an Anthem MRX 1120 / 720 / 520 / AVM 60 over RS232.

Usage:
    python -m anthem_rs232 /dev/ttyUSB0
    python -m anthem_rs232 /dev/ttyUSB0 --probe
    python -m anthem_rs232 /dev/ttyUSB0 --power on
    python -m anthem_rs232 /dev/ttyUSB0 --power off --zone 2
    python -m anthem_rs232 /dev/ttyUSB0 --volume -30
    python -m anthem_rs232 /dev/ttyUSB0 --mute toggle
    python -m anthem_rs232 /dev/ttyUSB0 --input 2
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


def _player_for(receiver: AnthemReceiver, zone: str):
    """Return the player matching ``--zone main|2``."""
    if zone == "main":
        return receiver.main
    if zone == "2":
        return receiver.zone_2
    raise ValueError(f"Unknown zone: {zone}")


async def _do_power(receiver: AnthemReceiver, action: str, zone: str) -> None:
    """Apply ``--power on|off``. ``zone=all`` uses Z0POW for all zones."""
    if zone == "all":
        if action == "on":
            await receiver.power_on_all()
            # If standby IP control is disabled, the receiver may need the
            # power-on command twice -- once to wake from low-power state.
            await asyncio.sleep(1.0)
            try:
                if not await receiver.main.query_power():
                    await receiver.power_on_all()
            except Exception:  # noqa: BLE001
                # Some firmwares ignore queries during the wake transition;
                # retry the power-on once unconditionally and move on.
                await receiver.power_on_all()
        else:
            await receiver.power_off_all()
        return

    player = _player_for(receiver, zone)
    if action == "on":
        await player.power_on()
        await asyncio.sleep(1.0)
        try:
            if not await player.query_power():
                await player.power_on()
        except Exception:  # noqa: BLE001
            await player.power_on()
    else:
        await player.power_off()


async def _do_mute(receiver: AnthemReceiver, action: str, zone: str) -> None:
    player = _player_for(receiver, zone)
    if action == "on":
        await player.mute_on()
    elif action == "off":
        await player.mute_off()
    else:  # toggle
        await player.mute_toggle()


async def _run(args: argparse.Namespace) -> None:
    port = args.port
    receiver = AnthemReceiver(port)

    print(f"Connecting to {port}...")
    try:
        await receiver.connect()
    except ConnectionError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    try:
        # Apply actions in a fixed, useful order: power first (so other
        # commands actually take effect), then input/volume/mute.
        if args.power is not None:
            print(f"Setting power: {args.power} (zone={args.zone})")
            await _do_power(receiver, args.power, args.zone)

        if args.input is not None:
            print(f"Selecting input: {args.input}")
            await _player_for(receiver, args.zone if args.zone != "all" else "main").select_input(args.input)

        if args.volume is not None:
            print(f"Setting volume: {args.volume:+.0f} dB")
            await _player_for(receiver, args.zone if args.zone != "all" else "main").set_volume(args.volume)

        if args.mute is not None:
            print(f"Setting mute: {args.mute}")
            await _do_mute(receiver, args.mute, args.zone if args.zone != "all" else "main")

        # Allow a moment for auto-report frames to land before we query state.
        if any(v is not None for v in (args.power, args.input, args.volume, args.mute)):
            await asyncio.sleep(1.0)

        print("Querying receiver state...")
        await receiver.query_state()
        _print_state(receiver.state)

        if args.probe:
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
        description="Control an Anthem MRX 1120 / 720 / 520 / AVM 60 over RS232",
    )
    parser.add_argument("port", help="Serial port (e.g. /dev/ttyUSB0) or serialx URL")
    parser.add_argument(
        "--power",
        choices=["on", "off"],
        help="Power the receiver on or off",
    )
    parser.add_argument(
        "--zone",
        choices=["main", "2", "all"],
        default="all",
        help="Target zone for actions (default: all for --power, main otherwise)",
    )
    parser.add_argument(
        "--input",
        type=int,
        metavar="N",
        help="Select input N (1-based)",
    )
    parser.add_argument(
        "--volume",
        type=float,
        metavar="DB",
        help="Set volume in dB (e.g. -30, 0, +5)",
    )
    parser.add_argument(
        "--mute",
        choices=["on", "off", "toggle"],
        help="Set mute state",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Probe configured inputs",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
