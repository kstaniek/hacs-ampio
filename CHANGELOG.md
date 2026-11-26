# Changelog

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
