# anthem-rs232

Async Python library for two Anthem RS-232 protocol generations:

- **Gen 2** (top-level package): MRX x10 (310/510/710), MRX x20 (520/720/1120), AVM 60. `;`-terminated, 115200 8N1, `Z?POW`/`Z?VOL`/`Z?MUT`/`Z?INP` zone-prefixed commands. Spec: Feb 2016.
- **Gen 1** (`anthem_rs232.gen1` subpackage): Statement D1/D2/D2v, AVM 20/30/40/50/50v, MRX 300/500/700. LF-terminated, 9600 or 19200 baud (per model), `P{zone}{verb}{arg}` shape. Command set ported from `rsnodgrass/python-anthemav-serial` (AVM-2 spec, 21 Nov 2000).

Modeled on `home-assistant-libs/denon-rs232`.

**Not supported**: STR amplifiers, Gen 4 (MRX 540/740/1140 + AVM 70/90 — different protocol with `GC*`, `NM*`, `SS*`, split `Z1ARC*` commands), MRX SLM (IP-only).

## Project structure

```
src/anthem_rs232/
  __init__.py    -- public exports for both generations (re-exports gen1)
  const.py       -- Gen 2 constants and enums
  protocol.py    -- Gen 2 parameter parsers/formatters, error reply parsing
  state.py       -- Gen 2 ReceiverState, MainZoneState, ZoneState, InputConfig
  players.py     -- Gen 2 MainPlayer (Z1) and ZonePlayer (Z2)
  receiver.py    -- Gen 2 AnthemReceiver: connect/query/event loop/dispatcher
  models.py      -- Gen 2 MRX_310/510/710/520/720/1120/AVM_60 definitions
  __main__.py    -- Gen 2 CLI: python -m anthem_rs232 PORT [--probe]
  gen1/
    __init__.py  -- Gen 1 public exports
    const.py     -- Gen 1 enums (Source, DecoderMode, EffectMode, ...) + baud/terminator
    protocol.py  -- Gen 1 parsers (compound zone status, single-field, error matcher)
    state.py     -- Gen 1 Gen1ReceiverState, MainZoneState, Zone2State, HeadphoneState
    receiver.py  -- Gen 1 Gen1Receiver + MainPlayer/Zone2Player/RecPlayer/Headphone/Tuner
    models.py    -- Gen 1 STATEMENT_D1/D2/D2V, AVM_20-50V, MRX_300/500/700

tests/
  conftest.py            -- Gen 2 MockSerialConnection, DEFAULT_QUERY_RESPONSES
  test_anthem_rs232.py   -- Gen 2 protocol parsers, control, queries, events, errors
  test_models.py         -- Gen 2 model definitions
  test_gen1.py           -- Gen 1 parsers, mocked receiver, all command tests
```

## Architecture

### Gen 2

- Uses `serialx` (`open_serial_connection`) for async serial I/O at **115200 8N1**.
- Framing: `<COMMAND><PARAM>;` (semicolon terminator). Queries append `?`: `Z1POW?;`.
- Successful set commands echo back. Queries return `<COMMAND><PAYLOAD>;`.
- Errors: `!E<orig>` (cannot execute), `!R<orig>` (out of range), `!I<orig>` (invalid command), `!Z<orig>` (zone off, system not in standby).
- `connect()` opens the port, verifies with `Z1POW?` (3-attempt retry for flaky proxies), then sends `ECH1;` to enable auto-reports.
- `query_state()` queries identification, inputs (`ICN?` + per-input `ISNyy?`/`ILNyy?`), and per-zone state.
- Background `_read_loop` parses `;`-terminated events; `state` returns a deep copy of `ReceiverState`. Per-message processing is exception-hardened (a malformed frame is logged and skipped, never kills the loop), the read task has a done-callback that tears down the connection if the loop ends while still connected, and an idle watchdog probes the link (`Z1POW?` Gen 2 / `?` identify Gen 1 -- both answered in standby) after `WATCHDOG_INTERVAL` (60 s) without RX, retrying up to `WATCHDOG_PROBE_ATTEMPTS` (3) times because ECO standby consumes the first frame as MCU wake-up (spec notes 10/11); an error reply counts as alive. Only when every probe goes unanswered does it tear down so the owner can reconnect. This covers transports (serial-over-network proxies) that die without delivering EOF or an exception. Read loops strip stray NUL bytes from incoming data: receivers emit them around ECO-standby transitions (~1 s after each response), and a NUL left in the buffer glues onto the next frame and silently breaks prefix matching.
- Subscribers receive `ReceiverState` on changes, `None` on disconnect.

### Gen 1

- Uses `serialx` at **9600 or 19200 baud** (per model — D2/D2v: 19200, others: 9600).
- Framing: ASCII commands LF-terminated. Multiple commands chainable with `;`.
- **Set commands return nothing on success** -- queries are the only reliable way to confirm state.
- Errors are verbose ASCII: `Invalid Command`, `Parameter Out-of-range`, `Main Off`, `Zone2 Off`, `Unit Off`, `Already in use`. Raised as `Gen1CommandError` on the matching pending query.
- `connect()` opens the port, sends `?` to identify (parses `(model,version,build)`), then sends `SST1` to enable Tx Status auto-report frames.
- `query_state()` issues `P1?`, `P2?`, `P3?`, `H?`, `TT?`.
- Pending queries use a **matcher callable** instead of a prefix string — the receiver may answer multiple message shapes for the same query (e.g. tuner can respond `TFT...` or `TAT...`).

## Key design decisions

### Gen 2

- Inputs are **numeric**, not enum values. Anthem inputs are user-configured; their names come from `ISN?`/`ILN?` and live in `state.inputs`.
- **One query/response model**: every query returns exactly one response (or one error).
- Prefix matching is longest-first (`_PREFIXES_BY_LEN`).
- `Z0POW` events update both zones + a synthesized aggregate `state.power` ("any zone on" → True; "all zones off" → False).
- Volume is integer dB only (per spec: "Entry is rounded to nearest valid value"). Format is `±NN` (e.g. `Z1VOL-35`, `Z1VOL+05`).
- Per-input settings (`SLIP` lip sync, `SDVS`/`SDVL` Dolby Volume) live on `InputConfig`; an event/report for input `00` is applied to the currently selected input. Pending queries are matched by `startswith`, so indexed query prefixes (`SPN1`, `SLIP02`, `Z1LEV3`) resolve even though the response-prefix table only holds the base command.

### Gen 1

- Inputs are **single-character codes** (`Source` enum: `0`-`9` + `d`-`j`). Map to display names via `model.source_map`.
- Volume is a **dB float with one decimal**. Main: 0.5 dB step (`P1VM`); Zone 2 / Headphone: 1.25 dB step (`P2V` / `HV`). Note Zone 2 uses `P2V` not `P2VM`.
- **Per-source decoder/effect modes** stored as `dict[source_code, DecoderMode]` / `dict[source_code, EffectMode]` on `MainZoneState` because the receiver remembers a different mode per source.
- The Rec / Zone 3 (`P3?`) only carries source -- modeled as `RecZoneState` with just `source`.
- Headphone path is a separate object (`Headphone` class) since it has its own `H?`/`HV`/`HM` commands.

## Testing

- `pytest` with `pytest-asyncio`, `asyncio_mode = "auto"`.
- Gen 2: `MockSerialConnection` in `conftest.py` -- real `asyncio.StreamReader`, mock writer; `_on_write` auto-responds to `?`-suffixed queries from `_query_responses`.
- Gen 1: `MockGen1Serial` in `test_gen1.py` -- same pattern, but matches against full command bytes (because Gen 1 has no universal "?" suffix), splits chained `;` commands before matching.
- 173 tests total: 95 Gen 2, 78 Gen 1.
- Run: `uv run pytest` or `python -m pytest tests/`

## Protocol references

- Gen 2: [Anthem MRX 1120 / 720 / 520 / AVM 60 IP / RS-232 serial commands](https://docs.google.com/spreadsheets/d/1_lN8JWSIPRrWrqxuZ3lNGy5GQ3FjyaBi6kIeuk21GP4/edit?usp=sharing) (Feb 2 2016).
- Gen 1: AVM-2 serial spec (21 Nov 2000) bundled in `rsnodgrass/python-anthemav-serial/docs/AVM-2-serial-programming.txt`. YAML command tables: `anthemav_serial/protocols/anthem_rs232_gen1.yaml`.
