# Native masked light groups

Implementation for aioampio 2.2.0 and hacs-ampio 0.6.0, 2026-11-26. The command format
passed live module tests. Automated tests cover HA group services and lifecycle;
the running dev instance also verifies group setup and received states.
Release aioampio 2.2.0 before the integration that pins it.

The relay extension in hacs-ampio 0.7.0 requires aioampio 2.3.0. Publish that library
before releasing an integration pinned to it. Use the local library override
for development until then.

## Intended behavior

Add a native Ampio group light alongside the existing individual light entities.
Home Assistant should expose `MLED Sofa` and keep `MLED Sofa 01` through
`MLED Sofa 06` independently controllable.

Calling the group sends one masked command directly to its module. It does not
call individual HA entities or require a collection window. Individual lights
retain their existing indexed commands. Existing HA helper groups keep their
behavior; users can replace their targets with the new native group where desired.

## Configuration

Add `light_groups` under a device, alongside its existing `lights` list. Members
reference existing local resource IDs, not HA entity IDs or editable names.
For device `can_id: 7775`, add:

```yaml
light_groups:
  - id: mled_kuchnia
    name: MLED Kuchnia
    area: Kuchnia
    members:
      - light1
      - light2
      - light3
      - light4
      - light5
      - light6
      - light7
      - light8
      - light9
      - light10

  - id: mled_sofa
    name: MLED Sofa
    area: Salon
    members:
      - light11
      - light12
      - light13
      - light14
      - light15
      - light16
```

Retain all 16 existing individual definitions. Derive the mask and feedback
dependencies from the referenced members. Users do not need to repeat feedback
topics or maintain a hexadecimal mask that could disagree with membership.

Validation rules:

- Group IDs must be unique within the device. Check generated resource-ID
  collisions before insertion; retain IDs across name and membership changes.
- Require a nonempty list of distinct existing ordinary lights on the same
  device. Reject nested groups, missing references, and cross-device members.
- Support MLED model 17 with non-RGBW dimmable members on outputs 1–16,
  and MREL8S model 4 with binary non-RGBW members on outputs 1–8. Each
  member must resolve to a unique command output within its module's range.
- Reject unknown fields and unsupported combinations during configuration
  validation, before starting the gateway. Do not truncate oversized indices.
- Permit overlapping groups; received member state updates all containing groups.

## Output mapping and wire format

The inspected [external configuration](https://raw.githubusercontent.com/kstaniek/ampio-config/refs/heads/main/ampio.yaml)
defines module `7775` (`0x1E5F`), model `17`, PCB `8`, firmware `11701`.
Kitchen uses `light1`–`light10`; Sofa uses `light11`–`light16`.

The existing command resolver takes the resource-ID numeric suffix and subtracts
one. Reuse this mapping and validate it before truncation. Names and binary
feedback indices do not determine output selection: `light1` has `binout.25`
feedback but selects command output 1, mask bit 0.

For one-based output `n`, set bit `n - 1`:

```python
mask = 0
for member in members:
    mask |= 1 << validated_command_index(member)
```

The local `goampiotcp/internal/ampio/ampio.go` provides an implementation
precedent: `AmpioSetValueWithMask = 0x14` and `SendValueWithMask()` encode:

```text
destination[4, big endian]  14  value[1]  mask[2, little endian]
```

Retain Python's extended sender arbitration ID `0x0F000000` and existing send
path. One eight-byte frame sets a common value on every selected output.

| Native group | Outputs | Mask | Full-on data | Frames |
| --- | --- | --- | --- | --- |
| MLED Kuchnia | 1–10 | `0x03FF` | `00 00 1E 5F 14 FF FF 03` | 1 |
| MLED Sofa | 11–16 | `0xFC00` | `00 00 1E 5F 14 FF 00 FC` | 1 |
| Garaż (module 6686) | 3, 5, 6 | `0x0034` | `00 00 1A 1E 14 FF 34 00` | 1 |

Sofa off is `00 00 1E 5F 14 00 00 FC`. Sofa brightness 128 is
`00 00 1E 5F 14 80 00 FC`. Unselected outputs must remain unaffected.

## Commands and brightness

Expose an MLED group as a normal dimmable HA light:

- `turn_on(brightness=x)` sends one masked command with value `x`.
- `turn_on()` sends the last successfully submitted nonzero group value, or
  255 when no such value is remembered.
- `turn_off()` sends one masked command with value 0 and retains the remembered
  nonzero group value.
- Zero brightness resolves to off. Initial scope does not advertise RGBW,
  transition, effect, or flash support.

Group brightness is a shared setpoint. One masked command cannot restore six
different member brightness levels. Group on intentionally sets all members
to the same level; individual control remains available afterward.

Remember group command brightness separately from aggregated feedback. Partial
reports must not overwrite the intended level. Update command memory only after
successful submission and serialize group calls to protect it. Memory is local
to the session, with 255 as the fallback after restart.

MREL8S groups expose HA's on/off color mode without brightness controls.
On sends value 255 and off sends 0; intermediate brightness values are rejected
by the library before sending. For module 6686, retain all eight individual
lights and add:

```yaml
light_groups:
  - id: garaz
    name: Garaż
    area: Garaż
    members: [light3, light5, light6]
```

`light3` is Garaż boczne (`binout.27`), `light5` Garaż środkowe
(`binout.29`), and `light6` Garaż tylne (`binout.30`). The generated resource
ID is `00001a1e_light_group_garaz`; YAML suggests entity ID `light.garaz`,
subject to normal registry collision handling. Off data is
`00 00 1A 1E 14 00 34 00`.

## Feedback and availability

The group has no independent hardware feedback. Derive its state from ordinary
member resources, including changes through wall controls, individual HA
entities, and overlapping groups:

- On when at least one member is known on.
- Off only when every member is known off.
- Unknown when no member is known on and at least one member's power is unknown.
- Brightness is the rounded mean of known levels of members known on. It is
  unknown if none of those levels is known, and 0 when the group is known off.
  This applies to MLED groups; relay groups always have no brightness level.
- Availability follows the owning module and gateway through the existing
  watchdog. Missing initial feedback yields unknown state.

Determine member power using the same binary-state-first, analog-level-fallback
rule as `AmpioLight.is_on`. Successful submission updates command memory,
not reported state; actual RX updates members and then groups.

Maintain a reverse index from member resource IDs to group IDs. Recompute
affected groups on member updates and emit normal resource-update events when
aggregate values change. Subscribe to member resource events instead of copying
their raw feedback topics: the current base controller maps a topic to one
resource, so copying topics could displace individual-light routing.

## Library and integration changes

Keep protocol encoding, membership resolution, and aggregation in `aioampio`,
independent of Home Assistant.

| File / component | Implementation |
| --- | --- |
| `aioampio/models/config.py` | Add `LightGroupCfg` and optional `DeviceCfg.light_groups`; validate membership and capability. |
| `aioampio/models/light.py` | Add resolved group-member metadata to light resources, empty for individual lights. Set group capabilities from validated members. |
| `aioampio/config.py` | Resolve ordinary lights first, then group resources with the same module owner and stable IDs such as `00001e5f_light_group_mled_sofa`. |
| `aioampio/controllers/lights.py` | Include groups in the public light collection. Route group commands before individual index extraction, compute the mask, and send one `0x14` command. Aggregate member resource updates and clean up subscriptions. |
| `hacs-ampio/custom_components/ampio/light.py` | Instantiate `AmpioMaskedLightGroup` for resources with members. Reuse state properties and module availability, with separate group-command brightness memory. |
| HACS entity registry handling | Apply group area as an initial entity-area suggestion without replacing user choices. Attach groups to the existing module device. |
| `hacs-ampio/custom_components/ampio/manifest.json` | Pin the released library version supporting native groups. |
| Both repositories' tests and documentation | Cover membership validation, encoding, aggregation, identity, lifecycle, and errors. |

Groups appear through `api.lights`. Their generated IDs must bypass the current
individual numeric-suffix parser. Existing individual unique IDs remain intact;
renaming a group or changing membership does not replace its HA entity.

Use the existing single-frame helper and TX accounting. Await transport
acceptance and report failures through the existing HA action-error path.
Do not fan out to individual commands after a failed masked send, because its
delivery may be uncertain. One group command counts as one physical TX frame.
Remove subscriptions on teardown and rebuild them after reload. Do not replay
group commands automatically.

Library releases before 2.2.0 reject `light_groups`. Install the library and
integration changes before adding this key to external YAML. Use Reconfigure
to fetch and validate the new YAML. Existing configurations without groups
retain their current entities and command paths.
MREL8S groups specifically require library 2.3.0 or later.

## Validation and acceptance

The initial investigation used installed `aioampio==2.1.0` with mocked sends
to confirm the baseline: 16 individual lights, 10 indexed sends for Kitchen,
and 6 for Sofa. Native group tests now exercise real configuration resolution,
controllers, feedback events, HA entities, services, and registry lifecycle,
with gateway connections and CAN writes mocked.

Automated coverage:

- The example creates 16 individual lights and two additional dimmable group
  lights on the same module, with stable unique IDs.
- Sofa on/off/brightness each send exactly one expected masked frame; member
  commands retain their indexed path. Group actions do not call member HA
  services or send additional indexed frames.
- Validate missing/duplicate members, duplicate physical outputs, ID collisions,
  unsupported models, nested groups, and output bounds including bits 0 and 15.
- Individual and external feedback update groups. Cover overlapping membership,
  mixed power, unknown startup, differing levels, missing brightness, module
  availability, and reconnect recovery.
- Feedback remains routed to individual resources. Partial reports cannot
  corrupt remembered group command brightness.
- Errors propagate without optimistic success or individual-command fallback;
  failed sends preserve command memory and TX counts reflect physical sends.
- Name/membership changes preserve identity; reload removes subscriptions and
  configuration rejection preserves the previous working entry.

Live command acceptance on module 7775 (model 17, PCB 8, firmware 11701) passed
on 2026-11-26. Both masks were sent with values 255 (on), 0 (off), and 128
(brightness), one frame per action. Module RX reported the requested levels on
all selected outputs. The user confirmed visible on/off and dimming behavior.
A Kitchen activation during the Sofa-off test was attributed by the user to
an automation. Kitchen was restored to its original 26/255 level and Sofa to
off, verified through RX. No integration or external configuration was changed
by these wire-format tests.

Live HA entity acceptance remains separate from this command acceptance.
Automated tests cover implemented entity lifecycle, commands, and aggregation.
The implemented library aggregation was additionally checked against real
module feedback in a receive-only session: eight RX frames populated all 16
member levels and both groups, with zero TX frames.
The existing development HA instance was then restarted with the local library
and cached group definitions. Its authenticated API confirmed both group
entities, correct areas, off states from feedback, and a zero module TX counter.

MREL8S command acceptance on module 6686 (model 4, PCB 5, firmware 10400)
passed on 2026-11-26. One masked ON frame (`00 00 1A 1E 14 FF 34 00`) and
one OFF frame (`00 00 1A 1E 14 00 34 00`) changed exactly outputs 3, 5, and 6.
RX confirmed each transition; the user confirmed the visible changes.
The other five relay outputs stayed off, and the original all-off state was
restored. This verifies on/off operation on this module/firmware.
