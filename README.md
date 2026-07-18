# anthem-rs232

Async Python library for the Anthem RS-232 protocol family — covers the **Gen 2** receivers (Statement-replacement MRX 310 through MRX 1120, AVM 60) and the older **Gen 1** receivers (Statement D1/D2/D2v, AVM 20–50, MRX 300/500/700). Built on [serialx](https://github.com/puddly/serialx).

Modeled on [denon-rs232](https://github.com/home-assistant-libs/denon-rs232); Gen 1 command set ported from [rsnodgrass/python-anthemav-serial](https://github.com/rsnodgrass/python-anthemav-serial).

## Supported hardware

| Model(s)                   | Series      | Constants                          | RS232 |
|----------------------------|-------------|------------------------------------|-------|
| Statement D1               | d1          | `STATEMENT_D1`                     | Gen 1 |
| Statement D2, D2v          | d2 / d2v    | `STATEMENT_D2`, `STATEMENT_D2V`    | Gen 1 |
| AVM 20, AVM 30, AVM 40     | avm20–avm40 | `AVM_20`, `AVM_30`, `AVM_40`       | Gen 1 |
| AVM 50, AVM 50v            | avm50       | `AVM_50`, `AVM_50V`                | Gen 1 |
| MRX 300, MRX 500, MRX 700  | mrx         | `MRX_300`, `MRX_500`, `MRX_700`    | Gen 1 |
| MRX 310, MRX 510, MRX 710  | mrx1        | `MRX_310`, `MRX_510`, `MRX_710`    | Gen 2 |
| MRX 520, MRX 720, MRX 1120 | mrx2        | `MRX_520`, `MRX_720`, `MRX_1120`   | Gen 2 |
| AVM 60                     | avm60       | `AVM_60`                           | Gen 2 |

Gen 1 constants live in `anthem_rs232.gen1`; Gen 2 in `anthem_rs232.models`.

The two generations use different wire formats and have separate receiver classes:

```python
# Gen 2 (semicolon-terminated, 115200 baud)
from anthem_rs232 import AnthemReceiver
from anthem_rs232.models import MRX_1120
gen2 = AnthemReceiver("/dev/ttyUSB0", model=MRX_1120)

# Gen 1 (LF-terminated, 9600 / 19200 baud per model)
from anthem_rs232 import Gen1Receiver
from anthem_rs232.gen1 import STATEMENT_D2
gen1 = Gen1Receiver("/dev/ttyUSB0", model=STATEMENT_D2)
```

### Not supported

- **STR amplifiers** — Gen 2 protocol family but not validated against this library.
- **Gen 4** — MRX 540 / 740 / 1140 + AVM 70 / 90. Substantially different protocol (new `GC*`, `NM*`, `SS*`, split `Z1ARC*` sub-commands; tuner removed).
- **MRX SLM** (2024+) — IP-only.

## Installation

```bash
pip install anthem-rs232
```

Requires Python 3.12+.

## Quick start

```python
import asyncio
from anthem_rs232 import AnthemReceiver, AudioListeningMode

async def main():
    receiver = AnthemReceiver("/dev/ttyUSB0")
    await receiver.connect()
    await receiver.query_state()

    print(f"Model: {receiver.state.model}")
    print(f"Power: {receiver.state.power}")
    print(f"Volume: {receiver.state.main_zone.volume} dB")
    print(f"Input: {receiver.state.main_zone.input_index}")

    await receiver.main.set_volume(-30.0)
    await receiver.main.select_input(2)
    await receiver.main.set_audio_listening_mode(AudioListeningMode.DOLBY_SURROUND)

    await receiver.disconnect()

asyncio.run(main())
```

## CLI

```bash
# Detect which Anthem model + protocol generation is on the wire (auto-tries
# Gen 2 @ 115200, Gen 1 @ 9600, Gen 1 @ 19200)
python -m anthem_rs232.probe /dev/ttyUSB0

# Query and print receiver status (Gen 2)
python -m anthem_rs232 /dev/ttyUSB0

# Probe configured inputs (uses ICN? + ISN?/ILN?)
python -m anthem_rs232 /dev/ttyUSB0 --probe
```

## Detecting the model

If you don't know which receiver is on a serial port (or which generation), use `probe()`:

```python
from anthem_rs232 import probe

result = await probe("/dev/ttyUSB0")
# result.generation  -> 1 or 2
# result.model_name  -> "MRX 1120"
# result.baud_rate   -> 115200
# result.model       -> the matching model constant (MRX_1120) or None

if result is None:
    print("No Anthem responded")
else:
    print(f"{result.model_name} (Gen {result.generation}, {result.baud_rate} baud)")
```

The probe walks Gen 2 (115200, `IDM?` then `Z1POW?` fallback) → Gen 1 @ 9600 (`?\n`) → Gen 1 @ 19200, and returns the first match. Works against the same port strings the receivers accept (local devices, `socket://`, `esphome://`).

## Features

### Full state after query

`connect()` opens the serial port, verifies the link with `IDM?`, and enables auto-reports with `ECH1`. Call `query_state()` to populate the current receiver state into the `state` property — after that, state stays current via auto-report events from the receiver.

```python
receiver = AnthemReceiver("/dev/ttyUSB0")
await receiver.connect()
await receiver.query_state()

state = receiver.state
state.model                  # "MRX 1120"
state.software_version       # "0.2.3"
state.power                  # True if any zone is on
state.front_panel_brightness # FrontPanelBrightness.MEDIUM
state.inputs                 # {1: InputConfig(...), ...}

mz = state.main_zone
mz.power                # True / False
mz.input_index          # 1
mz.volume               # -35.0
mz.mute                 # True / False
mz.arc_enabled          # True / False
mz.balance              # 0-100, 50 = center
mz.audio_listening_mode # AudioListeningMode enum
mz.audio_input_format   # AudioInputFormat enum
mz.video_input_resolution # VideoInputResolution enum
```

### Event subscription

Subscribe to state changes. Callbacks receive a `ReceiverState` snapshot on updates, or `None` when the connection drops.

```python
def on_change(state):
    if state is None:
        print("Disconnected!")
        return
    print(f"Volume: {state.main_zone.volume} dB")

unsub = receiver.subscribe(on_change)
unsub()  # stop receiving
```

### Power

```python
await receiver.power_on_all()    # Z0POW1 -- power all zones on
await receiver.power_off_all()   # Z0POW0 -- system standby
await receiver.main.power_on()   # Z1POW1
await receiver.main.power_off()  # Z1POW0
on = await receiver.main.query_power()
```

### Volume

Volume is in dB and rounded to the nearest valid value by the receiver.

```python
await receiver.main.set_volume(-30.0)  # Z1VOL-30
await receiver.main.set_volume(5.0)    # Z1VOL+05
await receiver.main.volume_up()        # Z1VUP01 (1 dB step)
await receiver.main.volume_up(step=5)  # Z1VUP05
await receiver.main.volume_down(step=2)
db = await receiver.main.query_volume()
```

### Mute

```python
await receiver.main.mute_on()
await receiver.main.mute_off()
await receiver.main.mute_toggle()
```

### Inputs

Anthem inputs are configurable and identified by 1-based index. Names come from `ISN?` (short) and `ILN?` (long) and are populated during `query_state()`.

```python
await receiver.main.select_input(2)
idx = await receiver.main.query_input()

inputs = receiver.state.inputs
print(inputs[1].short_name)   # "CBL"
print(inputs[1].long_name)    # "Cable Box"
```

### Audio listening mode

```python
from anthem_rs232 import AudioListeningMode

await receiver.main.set_audio_listening_mode(AudioListeningMode.DOLBY_SURROUND)
await receiver.main.audio_listening_mode_next()
mode = await receiver.main.query_audio_listening_mode()
```

### Anthem Room Correction

```python
await receiver.main.arc_on()
await receiver.main.arc_off()
on = await receiver.main.query_arc()
```

### Per-input processing

Lip sync delay, Dolby Volume, and the Dolby Volume Leveler are stored per
input on the receiver. ``input_index=0`` (the default) targets the currently
selected input.

```python
await receiver.set_lip_sync(50)                        # SLIP00050 (0-150 ms, 5 ms steps)
await receiver.set_dolby_volume(True, input_index=2)   # SDVS021
await receiver.set_dolby_volume_leveler(5)             # SDVL005 (0 = off, 1-9)

ms = await receiver.query_lip_sync()
on = await receiver.query_dolby_volume()
level = await receiver.query_dolby_volume_leveler()

# Populated per input from query replies and auto-reports:
receiver.state.inputs[2].lip_sync_ms
receiver.state.inputs[2].dolby_volume
receiver.state.inputs[2].dolby_volume_leveler
```

### Balance, channel levels, tone

These are runtime adjustments meant to compensate for source material — for system setup, use the receiver's setup menu and ARC.

```python
from anthem_rs232 import Channel

await receiver.main.set_balance(50)    # 0=full left, 100=full right
await receiver.main.set_channel_level(Channel.SUBS, -3.0)
await receiver.main.set_channel_level(Channel.HEIGHTS_1, 2.0)
await receiver.main.channel_level_up(Channel.CENTER)

await receiver.main.set_bass(-2.0)
await receiver.main.set_treble(3.0)
```

### Tuner (FM)

```python
await receiver.main.set_fm_frequency(105.50)   # T1FMS105.50
await receiver.main.tune_up()
await receiver.main.seek_up()
await receiver.main.preset_up()
await receiver.main.select_preset(7)
await receiver.main.assign_preset(7)
await receiver.main.remove_preset(7)
freq = await receiver.main.query_fm_frequency()
```

### Zone 2

```python
await receiver.zone_2.power_on()
await receiver.zone_2.select_input(2)
await receiver.zone_2.set_volume(-40.0)
await receiver.zone_2.mute_on()
```

### Setup / display

```python
from anthem_rs232 import FrontPanelBrightness

await receiver.set_front_panel_brightness(FrontPanelBrightness.HIGH)
await receiver.set_standby_ip_control(True)   # required for IP power-on
await receiver.set_speaker_profile(2)
await receiver.main.display_message(0, "Hello")
await receiver.main.open_setup_menu()
```

### Triggers

```python
await receiver.set_trigger_control(1, rs232_controlled=True)
await receiver.set_trigger(1, on=True)
```

### Connection handling

- If `IDM?` is not answered during `connect()`, `ConnectionError` is raised.
- If the serial connection drops, subscribers receive `None` and `connected` becomes `False`.
- An idle watchdog probes the link (`Z1POW?`, answered even in standby) after 60 s without RX and tears the connection down if repeated probes go unanswered — covering transports (e.g. serial-over-network proxies) that can die without delivering EOF. The probe retries up to 3 times because a unit in ECO standby consumes the first frame as its wake-up.
- Receiver errors come back as `!E/R/I/Z<original>;` and raise `CommandError` from the matching pending query. Fire-and-forget commands log the error.

```python
try:
    await receiver.connect()
except ConnectionError:
    print("Receiver not responding")
```

## Gen 1 (Statement / older AVM / older MRX)

The Gen 1 receiver lives in the `gen1` subpackage and exposes a different API surface (because the protocol is different — different command shape, different volume scale, dedicated headphone output, decoder/effect modes, channel trims).

```python
import asyncio
from anthem_rs232 import Gen1Receiver
from anthem_rs232.gen1 import (
    STATEMENT_D2, Source, DecoderMode, EffectMode, SleepTimer,
    DolbyDynamicRange, TunerMode,
)

async def main():
    rx = Gen1Receiver("/dev/ttyUSB0", model=STATEMENT_D2)
    await rx.connect()                 # opens serial, sends ?, enables SST1 auto-reports
    await rx.query_state()             # P1?, P2?, P3?, H?, TT?

    state = rx.state
    print(state.model, state.version)  # "Statement D2" "3.10"
    print(state.main_zone.volume)      # e.g. -30.5

    # Main zone (P1)
    await rx.main.power_on()           # P1P1
    await rx.main.set_volume(-30.5)    # P1VM-30.5  (0.5 dB step)
    await rx.main.mute_toggle()        # P1MT
    await rx.main.select_source(Source.DVD_1.value)   # P1S5
    await rx.main.set_decoder_mode("5", DecoderMode.PRO_LOGIC)
    await rx.main.set_effect_mode("5", EffectMode.HALL)
    await rx.main.set_dolby_dynamic_range(DolbyDynamicRange.LATE_NIGHT)
    await rx.main.set_sleep_timer(SleepTimer.SIXTY_MIN)
    await rx.main.display_message(1, "Hello")

    # Channel trims and balance (Main only)
    await rx.main.set_center_trim(1.5)
    await rx.main.set_sub_trim(-2.0)
    await rx.main.set_front_balance(2.0)
    await rx.main.set_master_bass(-3.0)

    # Zone 2 (P2) -- separate volume scale (1.25 dB step)
    await rx.zone_2.power_on()
    await rx.zone_2.set_volume(-50.0)  # P2V-50.0  (no "M" after V)
    await rx.zone_2.set_balance(2.5)
    await rx.zone_2.set_treble(4.0)

    # Rec / Zone 3 (P3) -- source-only
    await rx.rec.select_source(Source.TUNER.value)

    # Headphone (H) -- dedicated output
    await rx.headphone.set_volume(-20.0)
    await rx.headphone.mute_toggle()

    # Tuner (T)
    await rx.tuner.set_fm_frequency(101.5)   # TFT101.5
    await rx.tuner.set_am_frequency(540)     # TAT0540
    await rx.tuner.fm_preset(1, 2)           # TFP12
    band, freq = await rx.tuner.query_frequency()

    # 12 V triggers
    await rx.set_trigger(1, on=True)         # t1T1

    # System
    await rx.power_on_all()                  # P1P1;P2P1;P3P1
    await rx.lock_front_panel()              # FPL1
    await rx.rename_source("5", "Apple")     # SN5Apple
    await rx.save_user_settings()            # SfSU

    await rx.disconnect()

asyncio.run(main())
```

### Gen 1 notes

- **Wire format**: LF-terminated ASCII, default 9600 baud (D2/D2v: 19200). Multiple commands can be chained on one line with `;`.
- **No reply on success**: the Gen 1 receiver answers queries only — set commands are silent unless they fail. Connect enables Tx Status (`SST1`) so external state changes (front panel, IR remote, knob, bitstream change) propagate as auto-report frames.
- **Errors are verbose ASCII**: `Invalid Command`, `Parameter Out-of-range`, `Main Off`, `Zone2 Off`, `Unit Off`, `Already in use`. They raise `Gen1CommandError` from the matching pending query.
- **Volume**: dB float with one decimal place. Main zone uses 0.5 dB step (`P1VM`); Zone 2 / Headphone use 1.25 dB step (`P2V` / `HV`). The library snaps to the nearest grid.
- **Source codes**: single ASCII characters (`0`–`9`, plus `d`–`j` on D2/D2v for second-bank inputs). The `Source` enum lists them.
- **Identify**: `?` returns `(model,version,build)` — populated into `state.model` / `state.version` / `state.build_date` during `connect()`.

## Serial connection

**Gen 2** (MRX 310+, AVM 60): 115200 baud, 8N1, no flow control, `;`-terminated.
**Gen 1** (Statement, older AVM/MRX): 9600 or 19200 baud (per model), 8N1, no flow control, LF-terminated.
Both use a straight-wired DB-9 cable (Pin 2 = Tx, 3 = Rx, 5 = GND).

## Protocol references

- Gen 2: [Anthem MRX 1120 / 720 / 520 / AVM 60 IP / RS-232 serial commands (Google Sheets)](https://docs.google.com/spreadsheets/d/1_lN8JWSIPRrWrqxuZ3lNGy5GQ3FjyaBi6kIeuk21GP4/edit?usp=sharing)
- Gen 1: AVM-2 serial spec (21 November 2000) — bundled in the [rsnodgrass/python-anthemav-serial repo](https://github.com/rsnodgrass/python-anthemav-serial/blob/main/docs/AVM-2-serial-programming.txt)

## Development

```bash
uv sync
uv run pytest
```

## License

MIT
