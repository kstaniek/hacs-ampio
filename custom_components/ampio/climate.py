"""Ampio Climate."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from aioampio.controllers.events import EventType
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
)
from homeassistant.components.climate.const import ATTR_HVAC_MODE, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.temperature import display_temp

from .const import DOMAIN
from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.climates import ClimatesController
    from aioampio.models.climate import Climate
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .bridge import AmpioBridge, AmpioConfigEntry

PRESET_MODES = {"schedule": 0, "manual": 1, "temporary": 2, "holiday": 3}
HVAC_MODES = {HVACMode.AUTO: 0, HVACMode.HEAT: 1}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AmpioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up climate entities."""
    bridge = config_entry.runtime_data
    api = bridge.api
    controller: ClimatesController = api.climates
    make_climate_entity = partial(AmpioClimate, bridge, controller)

    @callback
    def async_add_climate(event_type: EventType, resource: Climate) -> None:
        """Add Climate."""
        async_add_entities([make_climate_entity(resource)])

    async_add_entities(make_climate_entity(climate) for climate in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_climate, event_filter=EventType.RESOURCE_ADDED)
    )


class AmpioClimate(AmpioBaseEntity, ClimateEntity):
    """Representation of an Ampio Climate."""

    entity_description = ClimateEntityDescription(
        key="ampio_climate",
        has_entity_name=False,
        translation_key="ampio_climate",
    )
    _attr_native_temperature_unit = "°C"
    _attr_supported_features = ClimateEntityFeature(0)

    def __init__(
        self, bridge: AmpioBridge, controller: ClimatesController, resource: Climate
    ) -> None:
        """Initialize Ampio Climate."""
        super().__init__(bridge, controller, resource)
        self._attr_hvac_modes = []
        supports_control = getattr(controller, "supports_control", None)
        self._writable = callable(supports_control) and supports_control(resource.id)
        if self._writable:
            self._attr_hvac_modes = list(HVAC_MODES)
            self._attr_preset_modes = list(PRESET_MODES)
            self._attr_supported_features = (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            )
            self._attr_min_temp = resource.min_temperature
            self._attr_max_temp = resource.max_temperature

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Use reported operating mode without inferring off from idle demand."""
        if self._writable:
            if self.resource.mode == 0:
                return HVACMode.AUTO
            return HVACMode.HEAT if self.resource.mode in (1, 2, 3) else None
        if self.resource.state is None:
            return None
        return HVACMode.HEAT if self.resource.state else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return heating activity without inferring that an idle zone is off."""
        if not self._writable and self.resource.state is False:
            return HVACAction.OFF
        if self.resource.heating is None:
            return None
        return HVACAction.HEATING if self.resource.heating else HVACAction.IDLE

    @property
    def native_current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.resource.current_temperature

    @property
    def native_target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self.resource.target_temperature

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        """Retain the read-only target attribute for existing templates."""
        return {
            "target_temperature": display_temp(
                self.hass,
                self.native_target_temperature,
                self.native_temperature_unit,
                self.precision,
            ),
        }

    @property
    def preset_mode(self) -> str | None:
        """Expose only confirmed numeric operating modes as presets."""
        if not self._writable:
            return None
        return next(
            (
                preset
                for preset, mode in PRESET_MODES.items()
                if mode == self.resource.mode
            ),
            None,
        )

    @property
    def target_temperature_step(self) -> float:
        """Match the display unit; commands are quantized to tenths Celsius."""
        return self.precision

    async def _async_set_state(self, **kwargs: Any) -> None:
        """Keep validation failures distinct from transport failures."""
        if not self._writable:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="climate_control_unavailable"
            )
        try:
            await self.async_command(
                self.controller.set_state(self.resource.id, **kwargs)
            )
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(str(err)) from err

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a native Celsius target, optionally followed by an explicit mode."""
        mode = None
        if ATTR_HVAC_MODE in kwargs:
            if kwargs[ATTR_HVAC_MODE] not in HVAC_MODES:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="invalid_climate_mode"
                )
            mode = HVAC_MODES[kwargs[ATTR_HVAC_MODE]]
        await self._async_set_state(temperature=kwargs.get(ATTR_TEMPERATURE), mode=mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Select calendar or manual heating; OFF is intentionally unavailable."""
        if hvac_mode not in HVAC_MODES:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_climate_mode"
            )
        await self._async_set_state(mode=HVAC_MODES[hvac_mode])

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Send one validated operating-mode transaction."""
        if preset_mode not in PRESET_MODES:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_climate_preset"
            )
        await self._async_set_state(mode=PRESET_MODES[preset_mode])
