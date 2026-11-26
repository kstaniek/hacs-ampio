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

With `aioampio==2.2.0`, add `light_groups` alongside a device's existing `lights`
in the external Ampio YAML. Each group creates an additional dimmable light;
its individual members remain independently controllable. Groups currently
support MLED modules (model 17) and outputs 1–16, with non-RGBW dimmable members.

For the Sofa outputs on module `can_id: 7775`:

```yaml
light_groups:
  - id: mled_sofa
    name: MLED Sofa
    area: Salon
    members: [light11, light12, light13, light14, light15, light16]
```

Member IDs refer to existing lights on that device. The library derives mask
`0xFC00` and sends exactly one frame for group on, off, or brightness. There is
no batching delay. Group brightness commands apply a common level to all members.

The group's YAML `name` supplies its entity name and initial entity ID:
`name: MLED Sofa` suggests `light.mled_sofa`, and `MLED Duża łazienka` suggests
`light.mled_duza_lazienka`. If an existing helper already owns the ID, HA adds a
suffix such as `_2`. Existing registered IDs and user-selected names are
preserved across reloads and YAML name changes. Replacing a helper while
reusing its ID requires an explicit migration after verifying the native group.

Plain on restores the last successfully submitted nonzero group brightness,
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
then use **Reconfigure** to download and validate the YAML. For local development
before publication, use `scripts/develop --aioampio ../aioampio`. The published
2.2.0 library is required for standard HACS installation. See
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

Climate entities currently provide read-only current temperature and heating
activity. HVAC mode remains unknown until explicit enabled/disabled feedback is
received; an idle heating zone is not treated as switched off. Temperature, HVAC
mode, and on/off controls are unavailable because `aioampio` does not implement
these commands yet. The target-temperature control is also hidden.

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

This release uses `aioampio==2.2.0`. The library remains independent of Home
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
