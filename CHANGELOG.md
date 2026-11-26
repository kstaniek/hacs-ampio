# Changelog

## 0.5.1

- Rebuild development setup around an isolated `.venv`, editable sibling Core
  when available, and the manifest-pinned aioampio wheel by default. Add explicit
  local-library and minimum-HA modes, dependency checks, and duplicate-port guards.
- Preserve development configuration and make integration links portable between
  the host and container without replacing another installation.
- Update the devcontainer to Python 3.14 with uv, native dependencies, and a
  separate venv volume. Align lint tooling and document the reproducible workflow.

## 0.5.0

- Add an enabled-by-default CAN Bridge **Reconnects** diagnostic counter using
  aioampio's transport retry metric. Publish only changes, immediately with the
  aioampio 2.1.0 notification API. Retain the last count while disconnected
  and reset on integration reload or HA restart.
- Require aioampio 2.1.0. Keep compatibility coverage for 2.0.2 fallback updates
  and the legacy 1.0.2 API.

## 0.4.0

### Breaking changes

- Expose read-only text status as sensors. Preserve registry preferences and
  create Repairs issues listing the old `text.*` and new `sensor.*` IDs. Update
  automations, scripts, and dashboards that reference the old IDs.

### Fixes

- Retry temporary gateway setup failures, wait for connection before loading
  platforms, and stop the transport on setup failures and Home Assistant shutdown.
- Translate transport failures into actionable Home Assistant service errors.
  Require aioampio 2.0.2 so rejected writes propagate instead of appearing successful.
- Suggest areas for new devices without overwriting user assignments or existing
  floor and area metadata during reload.
- Give gateway devices stable identifiers independent of the network endpoint.
  Add an optional gateway MAC and use DHCP/mDNS discovery to update known addresses.
- Recover legacy entries with missing or invalid bundled YAML through Reconfigure,
  with a Repairs issue explaining how to provide a configuration URL.

## 0.3.0

### Breaking changes

- Climate entities are read-only: temperature, HVAC-mode, and on/off controls are
  removed because the library does not implement their commands. Remove actions
  targeting these climate controls from automations and scripts.
- Climate state now represents enabled/disabled feedback and remains unknown when
  that feedback is missing. Use `hvac_action` (`heating` or `idle`) for automations
  based on heating activity. Idle heating is no longer reported as switched off.

### Fixes

- Preserve unknown alarm, light, and switch states until relevant feedback arrives.
  Partial alarm feedback no longer incorrectly reports the system as disarmed.
- Validate downloaded configuration through aioampio and check gateway connectivity
  before saving. Failed reconfiguration preserves the running entry and its data.
- Use standard HA position and motion properties for covers and valves, fixing
  toggle decisions and exposing the implemented cover tilt stop action.
- Keep aioampio pinned to 2.0.1; entity IDs are preserved.

## 0.2.1

- Preserve RGBW colour and brightness during rapid off/on switching and partial
  channel feedback. Require aioampio 2.0.1 for serialized, paced channel writes.

## 0.2.0

- Require aioampio 2.0.0 and add gateway/module traffic diagnostics and passive
  module availability monitoring.
- Improve configuration flows, translations, and CAN Bridge device metadata.

## 0.1.1

- Require aioampio 1.0.2, including the receive-worker fairness fix for queued CAN bursts.
- Support the published aioampio constructor and development interface/channel parameters.
- Create areas and floors before devices and entities, and preserve the bridge device during cleanup.
- Handle unknown alarm state and use Home Assistant's triggered state correctly.
- Update logging metadata and declare config-entry-only setup.
- Correct release packaging to include the Ampio integration.
