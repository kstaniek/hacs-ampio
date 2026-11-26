"""Support for Ampio Lights."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

from aioampio.controllers.events import EventType
from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityDescription,
    filter_supported_color_modes,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.util import color as color_util
from homeassistant.util import slugify

from .const import DOMAIN
from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.lights import LightsController
    from aioampio.models.light import Light
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .bridge import AmpioBridge, AmpioConfigEntry

ENTITY_FORMAT = f"{Platform.LIGHT}.ampio_{{}}"
# Allow for periodic RGBW feedback, without hiding external changes indefinitely.
RGBW_FEEDBACK_TIMEOUT = 30


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AmpioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up light entities."""
    bridge = config_entry.runtime_data
    api = bridge.api
    controller: LightsController = api.lights

    def make_light_entity(resource: Light) -> AmpioLight:
        """Expose native masked groups alongside their ordinary members."""
        entity_cls = (
            AmpioMaskedLightGroup if getattr(resource, "members", ()) else AmpioLight
        )
        return entity_cls(bridge, controller, resource)

    @callback
    def async_add_light(event_type: EventType, resource: Light) -> None:
        """Add Ampio Light."""
        async_add_entities([make_light_entity(resource)])

    async_add_entities(make_light_entity(light) for light in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_light, event_filter=EventType.RESOURCE_ADDED)
    )


class AmpioLight(AmpioBaseEntity, LightEntity):
    """Representation of an Ampio light."""

    _fixed_color_mode: ColorMode | None = None
    entity_description = LightEntityDescription(
        key="ampio_light",
        has_entity_name=False,
    )

    def __init__(
        self, bridge: AmpioBridge, controller: LightsController, resource: Light
    ) -> None:
        """Initialize the Ampio light."""
        super().__init__(bridge, controller, resource)
        self.resource = resource
        self.controller = controller
        supported_color_modes = {ColorMode.ONOFF}
        if resource.supports_color:
            supported_color_modes.add(ColorMode.RGBW)
        if resource.supports_dimming:
            supported_color_modes.add(ColorMode.BRIGHTNESS)
        # add color modes based on device

        supported_color_modes = filter_supported_color_modes(supported_color_modes)
        self._attr_supported_color_modes = supported_color_modes
        if len(self._attr_supported_color_modes) == 1:
            # If the light supports only a single color mode, set it now
            self._fixed_color_mode = next(iter(self._attr_supported_color_modes))
        self._last_brightness: int | None = None
        self._last_rgbw_color: tuple[int, int, int, int] | None = None
        self._rgbw_command_lock = asyncio.Lock()
        self._rgbw_target: tuple[int, int, int, int] | None = None
        self._rgbw_target_deadline = 0.0
        self.on_update()

        self.name = resource.name

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        if self.resource.supports_color:
            levels = self._rgbw_levels()
            return max(levels) if levels is not None else None
        return self.resource.state.get("brightness") if self.resource.state else None

    @property
    def is_on(self) -> bool | None:
        """Return power only when a binary or output-level report is known."""
        state = self.resource.state.get("state")
        if state is not None:
            return bool(state)
        if self.resource.supports_color:
            levels = self._rgbw_levels()
            return any(levels) if levels is not None else None
        if self.resource.supports_dimming and self.brightness is not None:
            return self.brightness > 0
        return None

    def _rgbw_levels(self) -> tuple[int, int, int, int] | None:
        """Read the actual output channel levels reported by Ampio."""
        values = tuple(
            self.resource.state.get(channel)
            for channel in ("red", "green", "blue", "white")
        )
        if any(value is None for value in values):
            return None
        return cast("tuple[int, int, int, int]", tuple(int(value) for value in values))

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Separate the reported channel ratios from overall brightness."""
        levels = self._rgbw_levels()
        if levels is None:
            return None
        if not any(levels):
            return self._last_rgbw_color or levels
        return cast(
            "tuple[int, int, int, int]", color_util.match_max_scale((255,), levels)
        )

    @callback
    def on_update(self) -> None:
        """Remember complete RGBW feedback, excluding partial command results."""
        if not self.resource.supports_color or (levels := self._rgbw_levels()) is None:
            return
        if self._rgbw_command_pending():
            if levels != self._rgbw_target:
                return
            self._rgbw_target = None
        self._remember_rgbw(levels)

    def _rgbw_command_pending(self) -> bool:
        """Wait for the commanded channels, with a bound for missing feedback."""
        if monotonic() >= self._rgbw_target_deadline:
            self._rgbw_target = None
        return self._rgbw_target is not None

    def _remember_rgbw(self, levels: tuple[int, int, int, int]) -> None:
        """Keep a nonzero color and brightness for subsequent on commands."""
        if any(levels):
            self._last_brightness = max(levels)
            self._last_rgbw_color = cast(
                "tuple[int, int, int, int]", color_util.match_max_scale((255,), levels)
            )

    async def _async_set_rgbw(self, levels: tuple[int, int, int, int]) -> None:
        """Send channels under the command lock and retain the requested color."""
        previous = self._last_brightness, self._last_rgbw_color
        self._rgbw_target = levels
        self._rgbw_target_deadline = monotonic() + RGBW_FEEDBACK_TIMEOUT
        self._remember_rgbw(levels)
        try:
            await self.async_command(
                self.controller.set_state(
                    id=self.resource.id, on=any(levels), color=levels
                )
            )
        except (Exception, asyncio.CancelledError):
            self._rgbw_target = None
            self._last_brightness, self._last_rgbw_color = previous
            raise

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        return self._fixed_color_mode or ColorMode.ONOFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get("brightness")
        if self.resource.supports_color:
            async with self._rgbw_command_lock:
                pending = self._rgbw_command_pending()
                color = kwargs.get("rgbw_color")
                if color is None:
                    color = self._last_rgbw_color if pending else self.rgbw_color
                    if color is None or not any(color):
                        color = self._last_rgbw_color or (255, 255, 255, 255)
                if brightness is None:
                    brightness = (
                        (self._last_brightness if pending else self.brightness)
                        or self._last_brightness
                        or 255
                    )
                levels = cast(
                    "tuple[int, int, int, int]",
                    tuple(round(value * brightness / 255) for value in color),
                )
                await self._async_set_rgbw(levels)
            return

        if self.resource.dimming and self._last_brightness and brightness is None:
            brightness = self._last_brightness
            self._last_brightness = None

        await self.async_command(
            self.controller.set_state(
                id=self.resource.id,
                on=True,
                brightness=brightness,
            )
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        if self.resource.supports_color:
            async with self._rgbw_command_lock:
                self.on_update()
                await self._async_set_rgbw((0, 0, 0, 0))
            return
        if self.resource.dimming:
            self._last_brightness = self.resource.state.get("brightness")

        await self.async_command(
            self.controller.set_state(
                id=self.resource.id,
                on=False,
            )
        )


class AmpioMaskedLightGroup(AmpioLight):
    """Control one module's light members with a single shared-value mask."""

    def __init__(
        self, bridge: AmpioBridge, controller: LightsController, resource: Light
    ) -> None:
        """Keep command intent separate from aggregated received brightness."""
        super().__init__(bridge, controller, resource)
        self._attr_name = resource.name
        self.entity_id = (
            f"{Platform.LIGHT}.{slugify(resource.name) or slugify(resource.id)}"
        )
        self._group_brightness = 255
        self._group_command_lock = asyncio.Lock()
        self._suggest_area = (
            er.async_get(bridge.hass).async_get_entity_id(
                Platform.LIGHT, DOMAIN, resource.id
            )
            is None
        )

    async def async_added_to_hass(self) -> None:
        """Suggest the group area only when its registry entry is first created."""
        await super().async_added_to_hass()
        if self._suggest_area and self.resource.area:
            areas = ar.async_get(self.hass)
            area = areas.async_get_area_by_name(self.resource.area)
            if area is None:
                area = areas.async_create(self.resource.area)
            er.async_get(self.hass).async_update_entity(self.entity_id, area_id=area.id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Apply one common level and remember it only after successful submission."""
        async with self._group_command_lock:
            if not self.resource.supports_dimming:
                await self.async_command(
                    self.controller.set_state(id=self.resource.id, on=True)
                )
                return
            brightness = kwargs.get("brightness")
            if brightness is None:
                brightness = self._group_brightness
            await self.async_command(
                self.controller.set_state(
                    id=self.resource.id, on=True, brightness=brightness
                )
            )
            if brightness:
                self._group_brightness = brightness

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the entire mask off while retaining the shared on level."""
        async with self._group_command_lock:
            await self.async_command(
                self.controller.set_state(id=self.resource.id, on=False)
            )
