# Heating-zone CAN command capture

## Scope and result

On 2026-11-27 at 00:11:38 Europe/Warsaw, an authorized MQTT experiment changed
zone 3 on module `00001b88` from 22.0 to 22.5 degrees Celsius and restored its
original setpoint and mode. All control commands went through the Ampio MQTT
server. A separate Waveshare connection recorded CAN traffic without sending
CAN frames.

The module's cached configuration identifies model 22, PCB 3, software 10559.
Those metadata were read from the configuration, not queried from firmware
during this experiment. These observations cover one module and one zone.

| Stage | MQTT command | CAN-reported setpoint | CAN-reported mode |
| --- | --- | --- | --- |
| Baseline | None | 22.0 | 0 |
| Test | `ampio/to/1b88/rs/3/cmd` with `22.5` | 22.5 | 2 |
| Restore | `ampio/to/1b88/rs/3/cmd` with `22.0`, then `ampio/to/1b88/rm/3/cmd` with `0` | 22.0 | 0 |

The first changed CAN report arrived approximately 87 ms after publication.
The final restored report matched the complete original eight-byte zone report.
Changing the target also changed mode 0 to mode 2, so restoring the temperature
alone is insufficient to restore the original operating mode.

## Setpoint command

Both observed commands used extended CAN arbitration ID `0x00000001` and DLC 8:

```text
22.5 C: 00 00 1B 88 13 02 E1 00
22.0 C: 00 00 1B 88 13 02 DC 00
```

The samples support this interpretation:

| Offset | Observed bytes | Interpretation |
| --- | --- | --- |
| 0-3 | `00 00 1B 88` | Destination module, big-endian address |
| 4 | `13` | Setpoint command |
| 5 | `02` | Zero-based zone index for zone 3 |
| 6-7 | `E1 00` or `DC 00` | Little-endian tenths of a degree: 225 or 220 |

Unlike the received temperature report, the command values have no 1000 offset.
Follow-up direct-CAN tests also confirmed 21.9 and 22.1, including tenth-degree
resolution. These positive samples do not establish the signed representation,
accepted limits, or rounding behavior for arbitrary inputs. The zone-index
interpretation still needs confirmation on another zone before generalization.

## Mode restoration command

MQTT `rm/3/cmd` with payload `0` produced these three extended CAN frames, again
with arbitration ID `0x00000001` and DLC 8:

```text
00 00 1B 88 16 00 02 0C
00 00 1B 88 16 01 08 02
00 00 1B 88 16 02 02 00
```

This exactly matches the existing aioampio
`generate_multican_payload(0x1b88, bytes.fromhex("08 02 02 00"))` helper:

- `16` is the multiframe envelope function; the following byte is its sequence.
- Sequence 0 carries two data chunks and checksum `0C`.
- Sequences 1 and 2 carry logical payload `08 02 02 00`.
- The additive checksum is `(08 + 02 + 02 + 00) & FF = 0C`.

Follow-up captures confirmed logical payloads `08 02 02 01`, `08 02 02 02`,
and `08 02 02 03`, with matching mode readback. The
`08 <zone-index> 02 <mode>` interpretation is supported for modes 0-3 on zone 3;
a second zone has not been tested.

## Feedback and restoration evidence

```text
Baseline: FE CB C6 04 C4 04 62 01
Changed:  FE CB C6 04 C9 04 62 21
Restored: FE CB C6 04 C4 04 62 01
```

The changed report contains target 22.5 and mode 2; the baseline and restored
reports contain target 22.0 and mode 0. Current temperature was 22.2 throughout
these reports. This verifies the reported controller state, not a physical
heating response during the brief experiment.

Afterward, the live Home Assistant API also reported target 22.0 and current
22.2 for `climate.zegar_ogrzewanie_3`. All 480 Ampio entities were present and
none were unavailable. Climate controls remained disabled in the integration.

## Evidence files and implementation limits

Local evidence is in the ignored directory
`.dev-config/backups/heating-control-20261126-231015/`:

- `can.jsonl`: all 2262 captured CAN frames with timestamps, identifiers and DLC.
- `mqtt.jsonl`: retained baseline and live setpoint updates.
- `events.jsonl`: publications and CAN confirmations.
- `command-frames.json`: the five extracted control frames.
- `result.json`: baseline, restoration and published commands.
- `ha-after.json`: final Home Assistant verification.

The source arbitration ID `0x00000001` belongs to the initial MQTT capture.
Follow-up tests below confirmed reception with aioampio's own controller ID
`0x0F000000`. The protocol experiments preceded the local climate implementation
described below.

The MQTT command names are documented in the
[official Ampio Node-RED integration guide](https://help.ampio.com/pl/poradniki-instalatora/integracja-systemu-ampio-z-node-red/).
The CAN byte sequences above come from this installation's capture.

## Follow-up direct-CAN validation

On 2026-11-27, the same zone was tested using extended sender ID `0x0F000000`.
Each operation was followed by restoration to 22.0 degrees Celsius and mode 0.
Successful acceptance required a fresh report from module `00001b88`, not only
a successful socket write or MQTT publication.

| Operation | Fresh module readback | Result |
| --- | --- | --- |
| Direct setpoint 22.1 | 22.1, mode 2 | Passed |
| Direct setpoint 21.9 | 21.9, mode 2 | Passed |
| Direct setpoint 22.5 | 22.5, mode 2 | Passed |
| MQTT modes 1, 2, 3 | Matching mode 1, 2, 3 | Passed |
| Direct modes 1, 2, 3 using captured payloads | Matching mode 1, 2, 3 | Passed |
| Direct return to mode 0 after each direct mode | Mode 0 | Passed |
| Setpoint and mode restoration after every operation | 22.0, mode 0 | Passed |

The direct run logged 21 outgoing CAN frames and received fresh module feedback
for all nine direct operations. The separate receiver did not observe those
outgoing frames under `0x0F000000`. Its capture contains the module's responses
and the MQTT restoration commands under `0x00000001`. Therefore, the direct TX
records are application logs; command acceptance is independently established
by the module's CAN readback.

### Mode 4 limitation

MQTT `rm/3/cmd` with `4` produced logical payload `08 02 02 04`, checksum `10`,
but no fresh zone report was observed during approximately 60 seconds. The
guarded test was then stopped and the baseline was restored and confirmed.
This does not establish whether mode 4 was ignored, applied without immediate
feedback, or has different semantics on this firmware. It was not replayed
through direct CAN and must not be exposed as a validated off/block command.

### Software validation

- aioampio library suite: 430 passed on Python 3.14.
- Integration suite with the minimum supported Home Assistant environment:
  205 passed.
- Integration suite with the running development Core environment: 205 passed.
- Ruff lint and formatting checks passed for the changed climate adapter and
  entity-contract tests; `git diff --check` passed.

These counts describe the protocol-validation stage before implementation.
The implementation tests and live service acceptance are recorded below.

### Heating-demand observation and final state

A final direct-CAN test held 22.5 degrees Celsius for at most 45 seconds, with
measured temperature 22.2. The module confirmed the new setpoint and mode 2,
but no report with the heating-demand bit set was observed in that interval.
This does not establish actuator behavior: the regulator's hysteresis, timing,
and other installation conditions were not independently checked. No physical
heating or relay-response acceptance is claimed.

After the hold, CAN confirmed target 22.0, mode 0, and the same heating-demand
flag as the baseline. The final Home Assistant API check confirmed target 22.0,
all 480 Ampio entities present, zero unavailable entities, and climate
`supported_features: 0`.

### Implementation readiness

The captured commands and direct module readback support implementing setpoint
writes at tenth-degree precision and modes 0-3 for the tested device. These
results do not validate mode 4 as an off/block control, explicit zone
enable/disable, negative temperatures, device-specific limits, or behavior on
other module/firmware versions. A writer should validate finite inputs and use
explicitly configured temperature limits; the tested 21.9-22.5 interval is not
the module's established minimum/maximum range. No extreme-temperature boundary
tests were performed on the occupied installation.

### Follow-up evidence

- `.dev-config/backups/heating-validation-20261126-232038/`: MQTT mode capture,
  the unconfirmed mode-4 operation, and confirmed baseline restoration.
- `.dev-config/backups/heating-validation-20261126-232220/`: direct-CAN tests,
  536 captured frames, the 21 direct TX records, operation results, and analysis.
- `.dev-config/backups/heating-validation-20261126-232308/`: the bounded demand
  observation, confirmed final restoration, live HA verification, and
  `validation-summary.json`.

The direct capture archive includes the experiment script and SHA-256 hashes.
No broker credentials are included in the evidence or this document.

## Full configurator transfer capture

On 2026-11-27, the user sent the full configuration from Ampio Configurator
while a persistent, receive-only observer recorded CAN and the MQTT mirror.
The capture was stopped gracefully after the user confirmed completion.

- Duration: approximately 81 seconds of CAN traffic.
- CAN: 2834 frames, including 627 frames addressed to `00001b88` from extended
  sender `0x0F000000`.
- MQTT: 7970 messages, including `hw/in`, `hw/out`, and `ampio/from/` traffic.
- No connection errors were recorded. JSONL sequence numbers are contiguous and
  file counts match the final recorder counters; this does not independently
  prove that the physical gateway dropped no traffic.
- The observer sent zero CAN frames and zero MQTT control publications.

### Reassembled configuration traffic

| Function | Recorded frames | Reconstruction |
| --- | --- | --- |
| `0E` | 378 | 16 zone records: eleven 63-byte records and five 4-byte records |
| `0C` | 67 | 132-byte indexed block followed by `0C FF` termination |
| `16` | 182 | Four complete envelopes plus six control frames |

For `0E`, sequence 0 carries the number of two-byte chunks followed by the
declared payload length. A full record starts with `0E 00 20 3F`: 32 chunks,
63 payload bytes, and one padding byte in the final CAN frame. A short record
starts with `0E 00 02 04`. Contiguous indices, declared lengths and padding were
verified. The record-integrity algorithm has not been identified; the second
header byte is a length, not the additive checksum used by function `16`.

All four `16` envelopes passed the existing additive-checksum interpretation.
Their payload lengths are 132, 35, 132 and 44 bytes. The indexed `0C` block has
contiguous indices 0 through 65; its integrity algorithm is not established.

### Candidate zone-setting fields

The full `0E` records suggest the following layout. These field meanings remain
candidates until independently compared with the configurator or its export.

| Payload offset | Candidate meaning | Zone 3 observation |
| --- | --- | --- |
| 0 | Zero-based zone index | `02` |
| 1 | Controller type | `01` |
| 2 | Zero-based temperature-sensor channel | `00` |
| 3-6 | Sensor module address, little-endian | `5F 6F 00 00` -> `00006f5f` |
| 8-9 | Comfort temperature, `(u16le - 1000) / 10` | `CE 04` -> 23.0 C |
| 10-11 | Economy temperature, same encoding | `C4 04` -> 22.0 C |
| 12 | Hysteresis in tenths of a degree | `05` -> 0.5 C |

The configured inventory independently identifies `00006f5f` as the Salon
temperature-sensor module, supporting the address interpretation. The five
short records have indices 11-15 and controller-type byte `00`, consistent with
unused zones 12-16, but their complete semantics are not established.

The possible 0.5-degree hysteresis is relevant to the earlier demand test:
22.5 target minus 22.2 measured was only 0.3 degrees. Without confirming the
hysteresis field and its activation semantics, the missing demand flag cannot
be treated as a failed setpoint command.

These configuration transfers do not establish a runtime enable/disable
command, configured temperature limits, or negative setpoint encoding.

### Configuration capture artifacts

The ignored directory
`.dev-config/backups/configurator-capture-20261126-232922/` contains:

- `can.jsonl` and `can.log`: structured and candump-style CAN records.
- `mqtt.jsonl`: original payload bytes and text, with retained/live markers.
- `status.json` and `events.jsonl`: final counters and connection history.
- `reassembled-transfers.json`: reconstructed payloads and integrity status.
- `transfer-control-frames.json`: configuration-transfer control frames.
- `zone-settings-candidates.json`: candidate fields for all 16 zone records.
- `analysis.json`, `sha256.json`, and `capture.py`: summary, integrity hashes,
  and the recorder source.

The capture is stopped. No configuration was replayed or modified by the
observer.

## Implemented local climate controls

The local aioampio controller now implements temperature writes and operating
modes 0-3 for model 22. It derives the channel from exactly one `heating.N`
topic, rejects inconsistent `zone.N` mappings, validates finite temperatures
against per-zone application limits, and serializes climate transactions. The
default limits are 7-35 degrees Celsius; they are not discovered hardware limits.
Commands round half-up to tenth-degree Celsius and do not update state
optimistically. Transmission failures stop later frames and propagate to HA.

The decoder retains the existing raw `mode` mask and adds normalized
`operating_mode` feedback. The climate resource exposes the normalized numeric
mode; unknown numeric modes are preserved so the adapter reports unknown rather
than a stale known mode.

The adapter exposes Auto/Heat and Schedule/Manual/Temporary/Holiday presets for
capable zones. A temperature-only write selects temporary mode through the
module's own behavior. The `target_temperature` attribute remains compatible
with existing templates alongside HA's standard `temperature` attribute.
Older libraries and unsupported modules retain read-only behavior. OFF/block,
on/off services, and cooling are unavailable.

Validation after implementation:

- Library: 480 tests passed, including captured frames, mode feedback, invalid
  input rejection, configured limits, concurrent commands and transport errors.
- Adapter with the new local library: 231 tests passed on minimum-supported HA
  and 231 passed on the running development Core environment.
- Adapter with the published 2.3.0 wheel: 205 passed and 26 new writer tests
  skipped, confirming the read-only fallback.
- Ruff checks and formatting passed for the implementation and new tests.

The local wheel was installed and Home Assistant restarted. Live service
acceptance began from the current morning baseline of 23.0 degrees Celsius and
Schedule mode. A 23.5 setpoint reported Temporary/mode 2; selecting Heat reported
Manual/mode 1; Holiday reported mode 3; Auto reported Schedule/mode 0. The test
then restored the exact 23.0/Schedule baseline. Each step required matching fresh
CAN feedback and HA state. All 480 Ampio entities remained present and available.

Evidence and the previous installed package are in
`.dev-config/backups/climate-implementation-20261127-071036/`, including
`service-acceptance.json`, `service-can.jsonl`, `service-events.jsonl`, the
wheel verification and package backup. This is a local build retaining version
2.3.0; a published library release and manifest update are still needed to
distribute the new controls. No release was published during this task.
