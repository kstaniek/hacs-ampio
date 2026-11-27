# Ampio Custom Component for Home Assistant

Ampio is a custom integration for Home Assistant that enables seamless communication with Ampio smart home devices. This integration allows you to monitor and control your Ampio system directly from Home Assistant, providing enhanced automation and convenience.

## Features

- Discover and control Ampio devices
- Monitor device states and sensor data
- Integrate Ampio devices into Home Assistant automations and dashboards

## Installation

### HACS (Recommended)

1. Go to **HACS > Integrations** in your Home Assistant UI.
2. Click the three dots in the top right and select **Custom repositories**.
3. Add this repository URL:  
    `https://github.com/kstaniek/hacs-ampio`
4. Select **Integration** as the category.
5. Search for "Ampio" in HACS and install the integration.
6. Restart Home Assistant.

### Manual

1. Download the `custom_components/ampio` directory from this repository.
2. Copy it into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

## Configuration

After installation, configure the integration via the Home Assistant UI:

1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for "Ampio".
3. Follow the setup instructions.

Setup and reconfiguration validate the downloaded YAML through `aioampio` and
check that the CAN gateway can connect. These checks send no device commands.
If validation or connection fails, the form reports the problem and keeps the
existing configuration and connection unchanged. Correct the input and retry.

The optional **Gateway MAC address** field accepts the Ethernet MAC shown on the
gateway's label or configuration page. Home Assistant can use a known MAC from
DHCP discovery to update the gateway address automatically. The integration also
accepts a MAC advertised by the gateway's CAN-server mDNS service. It does not
perform ARP lookups. If no MAC is available, leave this field blank and use
**Reconfigure** when the address changes. Existing gateway, module, and functional
entity registry IDs are retained across endpoint changes. Separate CAN ports on
the same gateway can have separate integration entries.

After startup, temporary gateway connection failures are retried automatically.
Invalid cached configuration requires correction through **Reconfigure**. If an
older entry has lost its bundled YAML, Home Assistant shows a Repairs issue;
provide a valid configuration URL to recover the existing entry.

## Entity feedback and controls

### Native masked light groups

With `aioampio==2.4.0`, add `light_groups` alongside a device's existing `lights`
in the external Ampio YAML. Each group creates an additional light; its individual
members remain independently controllable. MLED modules (model 17) support
dimmable non-RGBW members on outputs 1–16. MREL8S relay modules (model 4) support
binary on/off members on outputs 1–8.

For the Sofa outputs on module `can_id: 7775`:

```yaml
light_groups:
  - id: mled_sofa
    name: MLED Sofa
    area: Salon
    members: [light11, light12, light13, light14, light15, light16]
    members_enabled: true   # Optional; defaults to true
    members_visible: false  # Keep members active but hide them from automatic dashboards
```

Member IDs refer to existing lights on that device. The library derives mask
`0xFC00` and sends exactly one frame for group on, off, or brightness. There is
no batching delay. Group brightness commands apply a common level to all members.

`members_enabled` controls the initial Home Assistant enabled state of individual
members. It defaults to `true`. With `false`, their entities are still created in
the entity registry but disabled by the integration; the group stays enabled and
continues to receive member feedback. Members can be enabled manually in HA.
For overlapping groups, a member defaults to disabled if any containing group
sets `members_enabled: false`. Existing registry choices are preserved; changing
the YAML does not disable members that were already registered as enabled.
`members_visible` independently controls initial visibility and also defaults to
`true`. Use `members_enabled: true` and `members_visible: false` to show the group
on automatic dashboards while keeping individual member state, history, direct
controls and automations available. Hidden members are skipped by area, device
and label targets, preventing duplicate group/member commands. Explicit dashboard
cards can still show hidden entities. An overlapping group's `false` visibility
default takes precedence. Existing visibility choices and manual overrides are
preserved across reloads and YAML edits.

Both options require aioampio 2.4.0, which is included with integration 0.8.0.

For the three Garage relays on module `can_id: 6686`:

```yaml
light_groups:
  - id: garaz
    name: Garaż
    area: Garaż
    members: [light3, light5, light6]
```

This creates an on/off light, initially `light.garaz`, using mask `0x0034`.
It has no brightness control. Other relays on the module remain unaffected.

The YAML `name` supplies the entity name and initial entity ID for all configured
resources: `name: Komoda` creates `light.komoda` for a light. Polish characters
are transliterated, and empty names fall back to the stable Ampio resource ID.
An explicit resource `area: Salon` prefixes that ID, giving `light.salon_komoda`.
When the resource has no area (or only whitespace), use the owning module's YAML
area as a fallback. For example, an MSENS module with `area: Salon` and a sensor
named `Temperatura` creates `sensor.salon_temperatura`. An explicit sensor or
group area takes priority over the module's area.
When the area and name normalize to the same value, use it only once:
`area: Salon` and `name: Salon` give `light.salon`. User-selected HA area overrides
do not supply this prefix. The hardware module keeps its existing
device identifier, and the entity's unique ID remains its CAN/resource ID.

For example, CAN ID `0x1b88` and resource `id: climate3` produce unique ID
`00001b88_climate3`. Native groups use `00001b88_light_group_<group id>`.
Names and areas do not change these identities; keep CAN and resource IDs stable
to retain the same HA registry entries.

On the first startup with this naming fix, existing configured entities are
renamed once to match their YAML names and resolved areas, including IDs
previously based on the module name. Upgrading from 0.8.0 runs a second one-time
migration for resources with an explicit or module area; the earlier Repairs list remains
available. Registry identities, device associations, user names, icons, areas,
and disabled/hidden settings are retained. A Repairs notice lists the old and
new IDs; update references in automations, scripts, and dashboards. Diagnostic
sensor IDs are unchanged. Later manual ID changes and YAML name/area edits do not
trigger another migration.

For groups without an entity or module area, `name: MLED Sofa` suggests `light.mled_sofa`,
and `MLED Duża łazienka` suggests `light.mled_duza_lazienka`.
If an existing helper already owns the ID, HA adds a
suffix such as `_2`. After the one-time migration, registered IDs and
user-selected names are preserved across reloads and YAML name changes.
Replacing a helper while reusing its ID requires an explicit migration after
verifying the native group.

For dimmable MLED groups, plain on restores the last successfully submitted nonzero group brightness,
defaulting to 255 after startup. Off retains that remembered group level.

Group state follows actual member feedback, including individual HA commands,
wall controls, and automations. It is on if any member is known on, off only
when all members are known off, and otherwise unknown. Displayed brightness
is the rounded average of known levels of members that are on. Commands do not
optimistically change reported state. Overlapping groups are supported, and
availability follows the owning module and gateway.

The optional area is assigned when the group entity is first registered; later
user area choices are preserved. Keep group IDs stable when renaming or editing
membership to retain HA identity. Existing HA helper groups are separate;
update dashboard/automation targets to use a native group where desired.

Install the matching library/integration release before adding `light_groups`,
then use **Reconfigure** to download and validate the YAML. For local development,
use `scripts/develop --aioampio ../aioampio`. Standard HACS installation uses
the published aioampio 2.4.0 package. See
[the configuration and protocol details](docs/masked-light-commands.md).

### Upgrading to 0.4.0

Read-only text status resources move from `text.<name>` to `sensor.<name>`.
Their names, icons, areas, aliases, labels, and disabled/hidden settings are
preserved. Home Assistant cannot keep the same entity ID when its domain
changes. A Repairs issue lists each old and new ID; update affected automations,
scripts, and dashboard cards, then dismiss the issue. The sensor has no edit
control because `aioampio` does not support writing these values.

Area assignments from the Ampio configuration are suggestions for new devices.
Reloading leaves user-selected device/entity areas and existing floor/area
metadata unchanged, including areas the user has deliberately cleared.

`aioampio==2.0.2` raises a transport error when a CAN write fails or
the gateway is disconnected. The adapter translates these errors into a Home
Assistant action error and stops multi-frame commands at the failed frame.
Successful submission still does not confirm receipt by a module.

### Upgrading to 0.3.0

Climate entities are now read-only. Remove temperature, HVAC-mode, and on/off
actions targeting Ampio climate entities from automations and scripts. These
controls were previously displayed but failed when called because the library
does not implement the commands.

Review automations that use a climate entity's `heat` or `off` state to determine
whether heating is active. Use its `hvac_action` attribute (`heating` or `idle`)
for heating activity. The entity state represents HVAC mode and can be `unknown`
when enabled/disabled feedback is missing. Existing entity IDs are preserved.

Lights, switches, and alarms remain unknown until the relevant state is received.
An alarm report saying that no alarm is active does not establish that the system
is disarmed; disarmed requires explicit armed-state feedback. Covers and valves
report position and motion through Home Assistant's standard entity properties,
including the toggle and stop actions.

## Alarm control

Arming and disarming use the standard HA alarm actions and a numeric PIN.
Command status is a read-only sensor; its migration from the text platform
does not change alarm command encoding or routing.

aioampio 2.4.0 serializes alarm transactions and spaces their CAN fragments by
10 ms. On the validated Waveshare/Satel path, sending the same
nine-frame PIN command in a sub-millisecond burst produced no response; adding
the gap returned `OK` and started zone 3 arming. Install integration 0.8.0 and
restart HA to load the dependency and use the fix.

## Climate control

The adapter enables temperature and operating-mode control for M-RT modules
(model 22) when the installed aioampio build provides the validated climate
controller. Integration 0.8.0 pins `aioampio==2.4.0`, which includes the validated
writer. Restart HA after updating the integration to load the new dependency.

The writer requires exactly one `heating.N` state, for zone 1-16. A configured
`zone.N` state must agree. Commands use that topic's channel, independently of
the resource ID's suffix. Other module models and older library versions retain
the read-only behavior. The one-time naming migration described above applies
on upgrade; subsequent climate updates preserve registry identities.

| Control | Ampio mode | Behavior |
| --- | --- | --- |
| Auto / Schedule preset | 0 | Calendar operation |
| Heat / Manual preset | 1 | Manual operation |
| Temporary preset | 2 | Temporary manual operation |
| Holiday preset | 3 | Holiday operation |

Setting a temperature alone makes the module select temporary mode 2. A
`climate.set_temperature` call that also specifies `hvac_mode: auto` or `heat`
writes the setpoint first, then selects the requested mode. OFF, on/off services,
cooling, and block mode 4 are not exposed because they have not been validated.

Supported zones expose the normal thermostat target control. The additional
`target_temperature` attribute remains available for existing templates and for
read-only zones. It uses the same display unit and precision as current
temperature and is `null` before feedback arrives. Operating mode and presets
also remain unknown until reported; commands do not change state optimistically.
Heating activity follows the reported heating flag, independently of the
calendar/manual mode and the zone summary.

Commands round to the nearest tenth Celsius, with half-tenths rounded up.
Application limits default to 7-35 degrees Celsius; these are guardrails, not
discovered hardware limits. With the climate-capable library, set narrower
limits in the climate's YAML definition when appropriate:

```yaml
climates:
  - id: climate3
    name: Living room heating
    states: [heating.3, zone.3]
    min_temperature: 18.0
    max_temperature: 26.0
```

Limits must be ordered, non-negative, no higher than 100, and use tenth-degree
precision. The writer rejects non-finite temperatures, values outside those
limits, unsupported modes, and ambiguous zone mappings before sending frames.
The library remains independent of Home Assistant. The captured protocol and
its validation limits are documented in [Heating CAN control](docs/heating-can-control.md).

## Module traffic diagnostics

The CAN Bridge's **Device information** model line includes the active interface,
channel and network endpoint, for example:
`CAN Bridge (waveshare / can0, 172.31.11.67:20001)`.
The summary uses the same settings passed to `aioampio` and creates no additional
entity. Interface and channel selection is not configurable yet; the integration
currently uses `waveshare` and `can0`.
The bridge manufacturer is Waveshare; the attached CAN modules remain Ampio.
Integration entries use the same descriptive connection summary. Existing
endpoint-only titles are updated on setup; user-defined titles are preserved.

This release uses `aioampio==2.4.0`. The library remains independent of Home
Assistant; this integration owns diagnostic entities and availability policy.

With the new API, the CAN Bridge device has global **RX frames**, **TX frames**,
**Reconnects**, and **Last frame received** diagnostic sensors. Each configured
module has RX/TX counters and a last-frame timestamp, including modules without
other sensors. RX counts valid frames received from that module, even when their values are unchanged or their
payload type has no decoder. TX counts frames successfully sent by this bridge
to that module, including every fragment of a multi-frame command. It does not
count other controllers' commands and does not prove receipt by the module.
Counters survive gateway reconnects and reset on integration reload or restart.
**Reconnects** counts the library's transport retry cycles, including retries
that do not establish a connection. The initial connection is not a reconnect.
The counter remains readable while the gateway is disconnected and is enabled
by default. The module availability watchdog does not increment it or request
a reconnect.

The reconnect sensor updates only when its count changes. With the pinned
aioampio 2.1.0 notification API, HA receives each change immediately, independently
of traffic updates. Compatibility with aioampio 2.0.2 uses the existing one-second
availability check; unchanged values are not published. No additional polling
timer is created.

RX/TX counters and last-frame timestamps refresh every 30 seconds and remain
readable when a module is unavailable. **Last frame received** entities are
disabled by default to avoid frequent Activity and History entries. Enable them on the device's entity page
when troubleshooting. Disabling these entities does not affect the watchdog.
Existing enabled timestamp entities must be disabled separately in HA.
Last-frame timestamps record actual UTC reception time and remain
unchanged during silence or disconnection; they are unknown until the first
frame arrives. HA displays these timestamps in the user's local time. Gateway
counters use the library's global bridge metrics, including successful sends
that cannot be attributed to a configured module.

Open the integration's **Configure** options to change the default 60-second
silence timeout. Per-module overrides are a mapping of hexadecimal CAN IDs to
integer seconds, for example:

```yaml
"00001879": 120
"00001ecc": 0
```

Zero disables the silence timeout for that module (or globally). Overrides take
precedence over the global timeout. These options belong to Home Assistant;
do not add them to the external Ampio YAML configuration.

Availability is checked once per second using monotonic RX ages. A monitored
module needs fresh RX after startup or reconnect. After its timeout expires,
all functional entities belonging to it become unavailable; the next valid
frame restores availability even if no resource value changed. A reported
gateway disconnection affects all functional entities, including modules with
their silence timeout disabled.

Silence never requests a gateway reconnect with the new library defaults.
A crashed or unpowered module, or a broken CAN bus, can remain silent while
the TCP gateway connection is healthy. Reported socket/notifier failures and
explicit reconnect requests still recover the transport. Monitoring sends no
probes or device commands.

## Development

Install `uv`, then run `scripts/setup` and `scripts/develop`. When `../core` exists,
the scripts use that checkout in an isolated `.venv`; otherwise they use the
minimum supported HA release. The manifest-pinned aioampio wheel is the default.
Use `--aioampio ../aioampio` explicitly when developing the library too.
Existing `.dev-config` data is retained. See [TESTING.md](TESTING.md) for options,
tests, and the devcontainer workflow.

## Support

For issues or feature requests, please open an issue on the [GitHub repository](https://github.com/kstaniek/hacs-ampio/issues).

## License

By providing a contribution, you agree the contribution is licensed under Apache-2.0. This is required for Home Assistant contributions.


## Requirements

- **Ampio configuration must be provided via an external URL.**  
    Example configuration files are available at [kstaniek/ampio-config](https://github.com/kstaniek/ampio-config).

- **Waveshare 2-CH-CAN-TO-ETH gateway is required** for communication between Home Assistant and Ampio devices.
