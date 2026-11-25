# Changelog

## 0.1.1

- Require aioampio 1.0.2, including the receive-worker fairness fix for queued CAN bursts.
- Support the published aioampio constructor and development interface/channel parameters.
- Create areas and floors before devices and entities, and preserve the bridge device during cleanup.
- Handle unknown alarm state and use Home Assistant's triggered state correctly.
- Update logging metadata and declare config-entry-only setup.
- Correct release packaging to include the Ampio integration.
