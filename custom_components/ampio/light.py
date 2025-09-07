"""Support for Ampio Lights."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from aioampio.controllers.events import EventType
from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityDescription,
    filter_supported_color_modes,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback

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
    _attr_rgbw_color: tuple[int, int, int, int] | None = None

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

        self.name = resource.name

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        return self.resource.state.get("brightness") if self.resource.state else None

    @property
    def is_on(self) -> bool:
        """Return True if the light is on."""
        if not self.resource.state:
            return False
        state = self.resource.state.get("state") if self.resource.state else None
        return bool(state)

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the RGBW color of the light."""
        red = self.resource.state.get("red") if self.resource.state else None
        green = self.resource.state.get("green") if self.resource.state else None
        blue = self.resource.state.get("blue") if self.resource.state else None
        white = self.resource.state.get("white") if self.resource.state else None
        if any(v is None for v in (red, green, blue, white)):
            return None
        return red, green, blue, white

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        return self._fixed_color_mode or ColorMode.ONOFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get("brightness")
        color = kwargs.get("rgbw_color")
        if self.resource.dimming and self._last_brightness and brightness is None:
            brightness = self._last_brightness
            self._last_brightness = None

        if self.resource.color and color is None:
            self._attr_rgbw_color = color

        await self.controller.set_state(
            id=self.resource.id,
            on=True,
            brightness=brightness,
            color=color,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        if self.resource.dimming:
            self._last_brightness = self.resource.state.get("brightness")

        await self.controller.set_state(
            id=self.resource.id,
            on=False,
        )
