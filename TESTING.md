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

Repeat with `aioampio==2.0.0b2` for beta compatibility. This does not change the
integration manifest, which remains pinned to the stable library.

## Local development Core

Using the sibling Core checkout and its virtual environment:

```sh
../core/.venv/bin/python -m pip install -e ../core -e ../core/packages/pytest-homeassistant aioampio==2.0.0b2
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
