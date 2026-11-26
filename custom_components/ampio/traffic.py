"""Expose library traffic snapshots and monitor module availability."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from time import monotonic
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_MODULE_TIMEOUT,
    CONF_MODULE_TIMEOUTS,
    DEFAULT_MODULE_TIMEOUT,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from .bridge import AmpioBridge

DIAGNOSTIC_INTERVAL = 30


class ModuleTrafficMonitor:
    """Check cached RX ages without sending commands or requesting reconnects."""

    def __init__(self, bridge: AmpioBridge) -> None:
        """Initialize the monitor on the HA event loop."""
        self.bridge = bridge
        self.metrics = bridge.api.module_metrics
        self.gateway_metrics = bridge.api.metrics
        self.reconnects = self.gateway_metrics.reconnects
        self._push_reconnects = hasattr(bridge.api, "subscribe_reconnects")
        self._available: dict[int | None, bool] = {}
        self._listeners: dict[int | None, list[Callable[[], None]]] = defaultdict(list)
        self._diagnostic_listeners: list[Callable[[], None]] = []
        self._reconnect_listeners: list[Callable[[], None]] = []
        self._last_publish = monotonic()
        self._timeout = bridge.config_entry.options.get(
            CONF_MODULE_TIMEOUT, DEFAULT_MODULE_TIMEOUT
        )
        self._overrides = bridge.config_entry.options.get(CONF_MODULE_TIMEOUTS, {})

    @callback
    def start(self) -> None:
        """Start one shared timer, cleaned up when the entry unloads."""
        if self._push_reconnects:
            self.bridge.config_entry.async_on_unload(
                self.bridge.api.subscribe_reconnects(self._async_reconnects_changed)
            )
        self.async_refresh()
        self.bridge.config_entry.async_on_unload(
            async_track_time_interval(
                self.bridge.hass,
                self.async_refresh,
                timedelta(seconds=1),
                cancel_on_shutdown=True,
            )
        )

    @callback
    def available(self, can_id: int | None) -> bool:
        """Return the cached availability of a module or the gateway."""
        return self._available.get(can_id, False)

    @callback
    def subscribe(
        self, can_id: int | None, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Subscribe to availability transitions for one owner."""
        self._listeners[can_id].append(listener)
        return lambda: self._listeners[can_id].remove(listener)

    @callback
    def subscribe_diagnostics(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to counters published at a bounded frequency."""
        self._diagnostic_listeners.append(listener)
        return lambda: self._diagnostic_listeners.remove(listener)

    @callback
    def subscribe_reconnects(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to changes independently of the traffic publishing interval."""
        self._reconnect_listeners.append(listener)
        return lambda: self._reconnect_listeners.remove(listener)

    @callback
    def _async_reconnects_changed(self, count: int) -> None:
        """Publish only changed reconnect counts on the HA event loop."""
        if self.reconnects == count:
            return
        self.reconnects = count
        for listener in tuple(self._reconnect_listeners):
            listener()

    @callback
    def async_refresh(self, now: datetime | None = None) -> None:
        """Check availability, with throttling only for frame diagnostics."""
        if not self._push_reconnects:
            self._async_reconnects_changed(self.bridge.api.metrics.reconnects)
        metrics = self.bridge.api.module_metrics
        connected = self.bridge.api.connected
        available: dict[int | None, bool] = {None: connected}
        for can_id, snapshot in metrics.items():
            timeout = self._overrides.get(f"{can_id:08x}", self._timeout)
            age = snapshot.last_rx_age_s
            available[can_id] = connected and (
                timeout == 0 or (age is not None and age < timeout)
            )
        previous = self._available
        self._available = available
        for can_id, listeners in self._listeners.items():
            if previous.get(can_id) != available.get(can_id):
                for listener in tuple(listeners):
                    listener()
        if monotonic() - self._last_publish >= DIAGNOSTIC_INTERVAL:
            self.metrics = metrics
            self.gateway_metrics = self.bridge.api.metrics
            self._last_publish = monotonic()
            for listener in tuple(self._diagnostic_listeners):
                listener()
