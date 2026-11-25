# Testing the Home Assistant adapter

The protocol library remains independent of Home Assistant. CAN transport,
codecs, models, state notifications, watchdogs, and command encoders are tested
in `aioampio`. Home Assistant entities, registries, services, and config-entry
lifecycle are tested here using the official
[pytest-homeassistant package](https://github.com/home-assistant/core/tree/dev/packages/pytest-homeassistant).

## Minimum supported Home Assistant

Use Python 3.14 in a fresh virtual environment:

```sh
python -m venv .venv-tests
.venv-tests/bin/python -m pip install homeassistant==2026.11.0 pytest-homeassistant==2026.11.0 aioampio==1.0.2
.venv-tests/bin/python -m pytest -q
```

Repeat with `aioampio==2.0.0b3` for beta compatibility. This does not change the
integration manifest, which remains pinned to the stable library.

## Local development Core

Using the sibling Core checkout and its virtual environment:

```sh
../core/.venv/bin/python -m pip install -e ../core -e ../core/packages/pytest-homeassistant aioampio==2.0.0b3
../core/.venv/bin/python -m pytest -q
```

To test uncommitted library changes instead of an installed wheel:

```sh
PYTHONPATH="$(realpath ../aioampio)" ../core/.venv/bin/python -m pytest -q
```

CI tests both library versions with HA 2026.11.0 and development Core pinned to
`dc542e15890f1454c1fad76a1df3f4b8afa686dc`. Update the pinned revision deliberately
when advancing the development compatibility target.

## Test boundaries

The fixture uses the real library initialization, resources, controllers,
notifications, and command encoders. Only connection startup/shutdown and CAN
writes are mocked. No test contacts the gateway or actuates a physical device.
Config entries use a cached synthetic configuration, and HA dependency installation
is patched so each matrix job retains its explicitly selected library version.

Coverage includes all nine platforms' setup and state reporting, device/area
registration, light service commands and brightness restoration, reload without
listener leaks or registry identity changes, device removal, initialization
timeouts, and failed platform unloading. These automated checks do not establish
physical device behavior or replace an observed development-gateway test.

## Discovery and migration

Manual setup and discovery both require an HTTP(S) URL containing a YAML mapping.
Discovery offers a confirmation form with the advertised address and port filled
in; it never creates an entry automatically. Reconfiguration updates endpoint
identity while preserving the config-entry ID and bridge device registry ID.

Version 1 entries cache the bundled `custom_components/ampio/config.yaml` during
migration, retaining existing cached configuration when present. Migrated bundled
configurations have an empty configuration URL; provide a URL when reconfiguring
them. A missing or invalid bundled configuration leaves the original entry
untouched and reports migration failure.

Flow tests cover discovery confirmation and duplicates, input/download failures,
reconfiguration without extra reloads, and migration failure preservation.
English and Polish strings are checked for matching keys and placeholders.

The current acceptance policy is receive-only. Physical command checks and the
stable version 2 dependency upgrade remain deferred.

## RGBW brightness

HA color and brightness are combined into Ampio's four raw output channel levels
in the HA adapter. Brightness-only commands preserve the observed channel ratios;
off/on restores the last observed nonzero color and brightness. Feedback reports
integer brightness as the highest channel level and normalizes color independently.

RGBW tests exercise real HA light services and capture exact CAN frames with both
stable and beta libraries. Physical testing requires an explicitly designated
device; save its channel levels before sending commands and restore them afterward.
