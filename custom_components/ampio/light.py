"""Support for Ampio Lights."""

from __future__ import annotations

from functools import partial
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
from homeassistant.util import color as color_util

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.lights import LightsController
    from aioampio.models.light import Light
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .bridge import AmpioBridge, AmpioConfigEntry

ENTITY_FORMAT = f"{Platform.LIGHT}.ampio_{{}}"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AmpioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up light entities."""
    bridge = config_entry.runtime_data
    api = bridge.api
    controller: LightsController = api.lights
    make_light_entity = partial(AmpioLight, bridge, controller)

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
    def is_on(self) -> bool:
        """Return True if the light is on."""
        if not self.resource.state:
            return False
        state = self.resource.state.get("state")
        if state is None and self.resource.supports_color:
            levels = self._rgbw_levels()
            return any(levels) if levels is not None else False
        return bool(state)

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
        """Remember the last nonzero RGBW state for an off/on cycle."""
        if (
            self.resource.supports_color
            and (levels := self._rgbw_levels())
            and any(levels)
        ):
            self._last_brightness = max(levels)
            self._last_rgbw_color = self.rgbw_color

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        return self._fixed_color_mode or ColorMode.ONOFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get("brightness")
        if self.resource.supports_color:
            color = kwargs.get("rgbw_color")
            if color is None:
                color = self.rgbw_color
                if color is None or not any(color):
                    color = self._last_rgbw_color or (255, 255, 255, 255)
            if brightness is None:
                brightness = self.brightness or self._last_brightness or 255
            levels = tuple(round(value * brightness / 255) for value in color)
            await self.controller.set_state(id=self.resource.id, on=True, color=levels)
            return

        if self.resource.dimming and self._last_brightness and brightness is None:
            brightness = self._last_brightness
            self._last_brightness = None

        await self.controller.set_state(
            id=self.resource.id,
            on=True,
            brightness=brightness,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        if self.resource.supports_color:
            self.on_update()
        elif self.resource.dimming:
            self._last_brightness = self.resource.state.get("brightness")

        await self.controller.set_state(
            id=self.resource.id,
            on=False,
        )
