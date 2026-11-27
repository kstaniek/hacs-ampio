# Testing the Home Assistant adapter

The protocol library remains independent of Home Assistant. CAN transport,
codecs, models, state notifications, watchdogs, and command encoders are tested
in `aioampio`. Home Assistant entities, registries, services, and config-entry
lifecycle are tested here using the official
[pytest-homeassistant package](https://github.com/home-assistant/core/tree/dev/packages/pytest-homeassistant).

## Minimum supported Home Assistant

Install `uv`, then prepare an isolated environment with the minimum supported HA
version read from `hacs.json`:

```sh
scripts/setup --stable --venv .venv-tests --config .dev-config-tests
.venv-tests/bin/python -m pytest -q
```

Repeat with `aioampio==2.0.2` for fallback notification coverage and
`aioampio==1.0.2` for legacy compatibility. This does not change the
integration manifest, which is pinned to `aioampio==2.4.0`.
For example, install a test version with
`uv pip install --python .venv-tests/bin/python aioampio==2.0.2`, then run pytest
directly. Starting through `scripts/develop` restores the manifest pin.

## Local development Core

With `../core` present, setup installs that checkout and its official test fixtures
in editable mode into this repo's `.venv`. Core's own `.venv` is left untouched:

```sh
scripts/setup
.venv/bin/python -m pytest -q
scripts/develop
```

Without a sibling Core checkout, setup uses the minimum HA version instead.
Use `--core /path/to/core` to select another checkout. Python comes from Core's
`.python-version`, or this repository's pin in stable mode. Existing environments
with another Python version are rejected; choose a fresh path with `--venv`.

The default library is the published version pinned in the integration manifest.
Use an explicit option for uncommitted library changes:

```sh
scripts/setup --aioampio ../aioampio
.venv/bin/python -m pytest -q
scripts/develop --aioampio ../aioampio
```

Pass the same source options to setup and develop. Running without `--aioampio`
selects the published library again, even if the local checkout has the same
version. Local-library mode skips HA's automatic installation for aioampio only,
so HA cannot silently replace an editable install. Other integration dependencies
are still installed normally.

`scripts/develop --setup` refreshes dependencies and starts HA;
`scripts/develop --setup-only` prepares the environment without starting it.
Normal startup detects changed manifest pins, source choices, and broken imports,
and runs setup when needed. It prints the actual Python, HA, and library paths.
Ambient `PYTHONPATH`, `PYTHONHOME`, and active venv settings do not select imports.

The default configuration is `.dev-config`. Existing YAML, storage, and integration
entries are preserved. The scripts link this checkout into `custom_components` and
refuse to replace a different installed copy or link. Use `--config /path/to/config`
for another development configuration. An occupied HTTP port is rejected before
launch; stop the existing dev instance, or set another `http.server_port` in the
chosen YAML. `--debug` explicitly enables HA/asyncio debug mode.

If `uv` cannot download the pinned Python, check `command -v uv` and `uv --version`.
Update it using the manager that installed it, for example `mise upgrade uv` for a
mise-managed installation. `uv self update` applies only to standalone installs.

### Devcontainer

Rebuild the container after changing `.devcontainer.json` or `Dockerfile.dev`.
The container uses Python 3.14 and pinned uv, with FFmpeg, TurboJPEG, and libpcap
system dependencies. The parent workspace folder is mounted so sibling Core and
aioampio checkouts remain available. If Core is absent, stable setup still works.
A dedicated Docker volume holds `.venv`, separate from the host environment.
VS Code selects that interpreter. Run `scripts/develop` in the container terminal.
The container does not start HA automatically.
For an existing configuration with an absolute integration symlink, run
`scripts/setup` on the host once before opening the container. It converts a link
to this checkout into a relative link without replacing other installations.

The setup is for this adapter and its tests. Work on Core itself should follow
Core's own development instructions and bootstrap requirements.

CI tests all four library versions with HA 2026.11.0 and development Core pinned to
`dc542e15890f1454c1fad76a1df3f4b8afa686dc`. Update the pinned revision deliberately
when advancing the development compatibility target.

## Test boundaries

The fixture uses the real library initialization, resources, controllers,
notifications, and command encoders. Only connection startup/shutdown and CAN
writes are mocked. No test contacts the gateway or actuates a physical device.
Config entries use a cached synthetic configuration, and HA dependency installation
is patched so each matrix job retains its explicitly selected library version.

Coverage includes all eight platforms' setup and state reporting, device/area
registration, light service commands and brightness restoration, reload without
listener leaks or registry identity changes, device removal, initialization
timeouts, and failed platform unloading. These automated checks do not establish
physical device behavior or replace an observed development-gateway test.

## Discovery and migration

Manual setup and discovery both require an HTTP(S) URL containing a YAML mapping.
Discovery offers a confirmation form with the advertised address and port filled
in; it never creates an entry automatically. Reconfiguration updates endpoint
settings while preserving the config-entry ID and bridge device registry ID.
Version 3 entries use an optional normalized MAC plus port as their unique ID.
Without a hardware MAC, no network address is used as a persistent unique ID.
Gateway device identifiers use the stable config-entry ID. Version 2 gateway
identifiers are migrated in place, preserving existing devices and diagnostics.
Tests cover manual MAC input, duplicate endpoints, clearing/changing MAC
connections, and DHCP/mDNS address updates without changing registry identities.

Version 1 entries cache the bundled `custom_components/ampio/config.yaml` during
migration, retaining existing cached configuration when present. Migrated bundled
configurations have an empty configuration URL; provide a URL when reconfiguring
them. Missing or invalid bundled configuration produces a recoverable setup error
and a Repairs issue. Reconfiguration with a valid URL recovers the same entry;
tests verify that its functional entity registry identities survive.

Configured resource names and resolved YAML areas generate initial entity IDs
across all platforms. Naming tests cover Polish slugs, equal normalized name/area
values without duplication, empty names, duplicate names, and existing helper
collisions. An explicit resource area takes priority; otherwise, the owning
module's area supplies the prefix. Blank areas fall back as well. User-selected
HA areas do not affect the prefix. Tests cover all configured platforms, native
groups, legacy text-to-sensor migration, and two MSENS modules with repeated
sensor names. MSENS migration preserves registry UUIDs, unique IDs, device
associations, user areas, names, and disabled/hidden preferences across reloads.
Existing configured IDs are renamed once per naming version, with a persisted
migration marker and a Repairs notice listing the old and new IDs. Upgrading
from the 0.8.0 naming migration preserves its earlier Repairs map and migrates
only resources with an explicit or module area. Tests preserve registry
UUIDs, unique IDs, device associations, user names, disabled/hidden settings and
later manual ID choices across reloads. Diagnostic IDs and other entries are
excluded. Reconfiguration retains the migration marker.

Development acceptance on 2026-11-27 renamed 396 existing IDs, including
`light.oswietlenie_1` to `light.komoda`. Persisted registries retained all 521
Ampio registry UUIDs, unique IDs, device associations and user preferences;
124 diagnostic IDs were unchanged. The recorder contained fresh post-restart
states for all 480 enabled entities, with none unavailable. Registry backups,
the old/new ID CSV and verification receipts are kept under the ignored
`.dev-config/backups/entity-names-20261127-073040/` directory.

Read-only `text` resources now use the sensor platform. Migration copies registry
preferences and creates a Repairs issue naming the old and new entity IDs. An
existing target sensor is retained. This domain change requires users to update
entity references; sensor registry UUIDs cannot equal the old text registry UUIDs.

Flow tests cover discovery confirmation and duplicates, input/download failures,
reconfiguration without extra reloads, and recovery from missing legacy data.
English and Polish strings are checked for matching keys and placeholders.

Automated tests replace all physical I/O. The stable version 2 dependency and
RGBW command behavior were accepted separately on the explicitly authorized
module `00001879`, with its original output levels restored. This acceptance does
not establish physical behavior for other entity platforms. The 0.3.0 fixes were
checked in development HA without issuing device commands.

## RGBW brightness

HA color and brightness are combined into Ampio's four raw output channel levels
in the HA adapter. Brightness-only commands preserve the observed channel ratios;
off/on restores the last observed nonzero color and brightness. Feedback reports
integer brightness as the highest channel level and normalizes color independently.

RGBW tests exercise real HA light services and capture exact CAN frames with both
current and legacy libraries. Physical testing requires an explicitly designated
device; save its channel levels before sending commands and restore them afterward.

## Native masked light groups

Group tests require the aioampio 2.2.0 feature API and skip on older compatibility
libraries. They create ordinary lights and native group lights through real HA
setup, then exercise HA services against the library's real command encoder.
Only CAN I/O is replaced. Coverage includes exact one-frame on/off/brightness
payloads, independent indexed member commands, individual feedback propagation,
overlapping membership, unknown/mixed states, shared brightness memory, transport
failure, command ordering, module availability, and registry/area preservation.

Member-default tests require the `members_enabled` and `members_visible` fields
in an updated aioampio build. They cover independent omitted/true/false values on
MLED and relay groups, disabled members remaining registered, hidden members
continuing to report state and accept direct controls, continued group feedback,
single-frame group commands, overlap precedence independent of group order, and
manual enable/disable/show/hide choices surviving reloads. An area command with
hidden members sends only the native group mask. Changing either default does
not override an existing registry choice. Published libraries without the new
fields skip these cases.

The development preview on 2026-11-27 loaded all nine local YAML groups with
`members_enabled: true` and `members_visible: false`. It restored the 59 members
disabled by the earlier preview and hid them instead. Registry snapshots retained
all 527 Ampio identities and existing preferences outside those preview flags.
The recorder contained fresh states for all 486 enabled entities, including the
59 hidden members, with none unavailable. Backups and the verified local wheel
are under `.dev-config/backups/member-visibility-dev-20261127-091429/`.

The standalone library additionally validates masks and membership, catches
duplicate physical outputs and resource IDs, and tests dependency cleanup.
Run both repositories' suites with the matching local library before its release.
The integration dependency pin and CI matrix require aioampio 2.4.0 to be
published before integration 0.8.0 is released.

Relay group tests require aioampio 2.3.0 and skip on older compatibility libraries.
They cover binary-only HA controls, a sparse mask selecting outputs 3, 5, and 6,
individual indexed commands and feedback, and error propagation without fan-out.
The library also rejects unsupported relay brightness and output 9, while
accepting output 8. Both HA 2026.11.0 and development Core run the full suite.

Physical relay testing on module 6686 (MREL8S model 4, PCB 5, firmware 10400)
passed on 2026-11-26: one masked ON and one OFF frame changed exactly the three
Garage lights. RX and user observation confirmed both transitions. Other outputs
were unchanged and the original all-off state was restored.

Relay extension validation: 342 library tests passed; 203 integration tests
passed on each of HA 2026.11.0 and development Core. Ruff checks/formatting,
Pylint, and mypy passed for the changed code. The configuration passed yamllint
and library validation, with an additive comparison confirming only the Garage
group was added.

The existing dev HA was restarted with local aioampio 2.3.0 and the cached
Garage definition. Its authenticated API confirmed `light.garaz`, on/off-only
capability, Garage area, correct state from all three members, and a zero
module TX counter. All 102 previous light identities and areas were preserved.
The three members were on at verification; no command was sent by this
deployment. Live HA service transmission remains covered by synthetic tests
and the separately accepted physical wire-format tests above.

Physical command encoding was accepted separately on module 7775 (MLED model 17,
PCB 8, firmware 11701) on 2026-11-26. Kitchen mask 0x03FF and Sofa mask 0xFC00
each passed on, off, and brightness-128 commands, with one frame per action and
per-output RX verification. The user confirmed visible on/off and dimming
behavior; a Kitchen change during Sofa off was identified as an automation.
Kitchen was restored to 26/255 and Sofa to off. This acceptance tested the wire
commands, not the subsequently implemented HA group entity lifecycle.

A subsequent receive-only check initialized both native groups with the new
library against the actual module. Eight received frames populated all 16
member levels and both group states, with zero transmitted frames. This
verifies live library feedback aggregation; HA service/lifecycle coverage
remains synthetic.

The existing development HA instance was subsequently restarted with the local
2.2.0 library and the two groups added only to its cached configuration. The
authenticated HA API confirmed both native group entities were available, off
from member feedback, and assigned to Kitchen and Salon. The module TX counter
remained zero. This additionally verifies live HA group setup and state reporting;
implemented HA group command services remain covered by synthetic tests and the
separate physical command-format acceptance above.

Development startup tests reject an active HTTP listener with address reuse
enabled and permit immediate restart after a server-side connection close
leaves TIME_WAIT sockets on that port.

## Configuration UI serialization

Regression tests also validate YAML using the actual library before committing
configuration changes, mock only gateway connection I/O, and confirm failures
leave a running entry unchanged. Platform contract tests cover unknown feedback,
partial alarm flags, cover/valve position and motion, toggle decisions, and
rejection of unsupported climate controls.

Climate-capable library development adds `tests/test_climate_control.py` in both
repositories. The library tests compare setpoints and modes against captured CAN
vectors, validate limits and addressing, and exercise serialization and transport
failures. Adapter tests pass real raw frames through the decoder and controller,
exercise HA services and Fahrenheit conversion, reject OFF/block, and verify
that commands do not fabricate feedback. These tests require the local library;
they are skipped for older published wheels, whose read-only compatibility
remains covered by the existing entity-contract tests.

HTTP tests use HA's authenticated configuration endpoints to serialize manual,
reconfiguration, discovery, and error forms. They also submit reconfiguration to
refresh cached YAML. These tests catch validators that work in Python but cannot
be serialized into browser form fields.

## Transmission errors

`aioampio` 2.0.2 adds standalone `AmpioTransmissionError`, a
`ConnectionError` subclass. The real public send path and multi-frame command
failure behavior are tested with only the transport boundary mocked. Adapter
service tests verify translated `HomeAssistantError` for lights, switches,
covers, valves, and alarms. These five tests run against the pinned published
`aioampio==2.1.0` dependency and skip in the legacy 1.0.2 compatibility job.
CI verifies that the current dependency exports the exception before testing.

Lifecycle tests cover transient connection retries, invalid configuration,
post-start registration failures, and shutdown followed by unload without double
stopping. Registry tests preserve user area choices and floor metadata on reload.
All new checks are synthetic and issue no physical device commands.

## Reconnect diagnostic

The gateway reconnect sensor has a separate change subscription, so traffic
refreshes do not write its state. With the `subscribe_reconnects` API introduced
in aioampio 2.1.0, tests assert that a retry notification immediately updates the
HA state without calling the monitor or advancing time. The aioampio 2.0.2
compatibility job instead detects changed counts in the existing one-second
availability check. Tests cover both paths, unchanged-value suppression,
offline readability, subscription cleanup, and identity preservation on reload.

## Alarm command delivery

`tests/test_alarm_control.py` exercises zone-3 arm/disarm actions through HA
with the migrated read-only command-status sensor present. It checks all nine
fragments, their order and checksum, the zone-only mask `0x04`, independent
response feedback, and the absence of optimistic state changes. Library tests
check 10 ms gaps, serialized concurrent alarm transactions, and stopping after a
failed frame while releasing the transaction lock. Full validation passed with
502 library tests and 292 integration tests on both stable and development HA.

Live acceptance on 2026-11-27 used only zone 3 on module `00001ecc`. An unpaced
nine-frame burst with approximately 0.3 ms gaps produced no response and no
arming feedback. The identical payload and PIN with 10 ms gaps returned `OK`,
updated the status sensor, and entered `arming`. A paced disarm returned the
zone to disarmed. Zones 1 and 2 remained disarmed. The PIN and its encoded bytes
are omitted from evidence logs. This demonstrates a timing dependency; it does
not identify which historical commit first exposed it. The alarm encoder is
unchanged between aioampio 1.0.2 and 2.3.0.

When the user subsequently reported arming and failed disarming through the old
running dev build, testing stopped and a paced disarm confirmed `armed=false`,
`arming=false` and `arming_10s=false`. The tested fix was then installed as a
local wheel and dev HA restarted. Further arming tests were cancelled; a fully
armed-state acceptance test was not performed. Evidence is under
`.dev-config/backups/alarm-zone3-20261127-093131/`; the source snapshot, wheel,
package/registry backups and installation receipt are under
`.dev-config/backups/alarm-pacing-implementation-20261127-093717/`.
