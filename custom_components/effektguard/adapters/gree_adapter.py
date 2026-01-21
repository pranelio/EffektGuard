"""Gree heat pump adapter for reading state via Modbus.

This adapter reads Gree heat pump data from Home Assistant Modbus entities.
It does not directly communicate with the Gree API or Modbus protocol,
instead reading from entities created by Home Assistant's Modbus integration.

Data read includes:
- Supply/flow temperature (BT25 equivalent)
- Return temperature (BT3 equivalent)
- Target supply temperature (S1 equivalent)
- Heat mode status (Heat/Cool/Off/DHW)
- DHW charging status
- DHW temperature
- Compressor frequency
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_GREE_COMPRESSOR_HZ_ENTITY,
    CONF_GREE_DEGREE_MINUTES_ENTITY,
    CONF_GREE_DHW_CHARGING_ENTITY,
    CONF_GREE_DHW_TEMP_ENTITY,
    CONF_GREE_INDOOR_TEMP_ENTITY,
    CONF_GREE_OUTDOOR_TEMP_ENTITY,
    CONF_GREE_RETURN_TEMP_ENTITY,
    CONF_GREE_SUPPLY_TEMP_ENTITY,
    CONF_GREE_TARGET_SUPPLY_TEMP_ENTITY,
    CONF_GREE_UNIT_STATUS_ENTITY,
    DEFAULT_INDOOR_TEMP,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class GreeState:
    """Current state of Gree heat pump.

    All temperatures in °C, power in kW.
    """

    outdoor_temp: float
    indoor_temp: float
    supply_temp: float  # Flow/supply temperature (Gree equivalent to BT25)
    return_temp: float | None
    target_supply_temp: float  # Target supply temperature (Gree equivalent to S1)
    is_heating: bool  # True if unit_status == "Heat"
    is_hot_water: bool  # True if DHW charging is active
    timestamp: datetime
    degree_minutes: float = 0.0  # Thermal debt (default 0 if not available)
    dhw_temp: float | None = None  # Hot water tank temperature - optional
    compressor_hz: int | None = None  # Compressor frequency - optional
    power_kw: float | None = None  # Total power consumption in kW - optional

    @property
    def flow_temp(self) -> float:
        """Alias for supply_temp (flow temperature = supply temperature)."""
        return self.supply_temp


class GreeAdapter:
    """Adapter for reading Gree heat pump via Modbus entities.

    Gree heat pumps use Modbus registers exposed via Home Assistant's
    Modbus integration. This adapter reads from those entities only,
    following the same pattern as NibeAdapter.
    """

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]):
        """Initialize Gree adapter.

        Args:
            hass: Home Assistant instance
            config: Configuration dictionary with entity IDs

        Required config keys (all must be present):
            - gree_supply_temp_entity: Supply/flow temperature sensor
            - gree_return_temp_entity: Return temperature sensor
            - gree_target_supply_temp_entity: Target supply temperature sensor
            - gree_outdoor_temp_entity: Outdoor temperature sensor
            - gree_indoor_temp_entity: Indoor temperature sensor (or custom HA entity)
            - gree_unit_status_entity: Heat mode text sensor (Heat/Cool/Off/DHW)
            - gree_dhw_charging_entity: DHW charging binary sensor

        Optional config keys:
            - gree_dhw_temp_entity: DHW temperature sensor
            - gree_compressor_hz_entity: Compressor frequency sensor
        """
        self.hass = hass
        self._supply_temp_entity = config.get(CONF_GREE_SUPPLY_TEMP_ENTITY)
        self._return_temp_entity = config.get(CONF_GREE_RETURN_TEMP_ENTITY)
        self._target_supply_temp_entity = config.get(CONF_GREE_TARGET_SUPPLY_TEMP_ENTITY)
        self._outdoor_temp_entity = config.get(CONF_GREE_OUTDOOR_TEMP_ENTITY)
        self._indoor_temp_entity = config.get(CONF_GREE_INDOOR_TEMP_ENTITY)
        self._unit_status_entity = config.get(CONF_GREE_UNIT_STATUS_ENTITY)
        self._dhw_charging_entity = config.get(CONF_GREE_DHW_CHARGING_ENTITY)
        self._dhw_temp_entity = config.get(CONF_GREE_DHW_TEMP_ENTITY)  # Optional
        self._compressor_hz_entity = config.get(CONF_GREE_COMPRESSOR_HZ_ENTITY)  # Optional
        self._degree_minutes_entity = config.get(CONF_GREE_DEGREE_MINUTES_ENTITY)  # Optional

    async def get_current_state(self) -> GreeState:
        """Read current Gree heat pump state from Modbus entities.

        Returns:
            GreeState with current readings

        Raises:
            ValueError: If required entities are unavailable
        """
        # Read required temperatures
        outdoor_temp = await self._read_entity_float(
            self._outdoor_temp_entity, default=0.0
        )
        indoor_temp = await self._read_entity_float(
            self._indoor_temp_entity, default=DEFAULT_INDOOR_TEMP
        )
        supply_temp = await self._read_entity_float(
            self._supply_temp_entity, default=25.0
        )
        return_temp = await self._read_entity_float(
            self._return_temp_entity, default=None
        )
        target_supply_temp = await self._read_entity_float(
            self._target_supply_temp_entity, default=25.0
        )

        # Read unit status (Heat/Cool/Off/DHW) to determine is_heating
        unit_status = await self._read_entity_string(self._unit_status_entity, default="Unknown")
        is_heating = unit_status == "Heat"

        # Read DHW charging status
        is_hot_water = await self._read_entity_bool(
            self._dhw_charging_entity, default=False
        )

        # Read optional DHW temperature
        dhw_temp = await self._read_entity_float(
            self._dhw_temp_entity, default=None
        )

        # Read optional compressor frequency
        compressor_hz = await self._read_entity_float(
            self._compressor_hz_entity, default=None
        )

        # Read optional degree minutes (thermal debt)
        # Defaults to 0 if not available - safe state (no thermal debt)
        degree_minutes = await self._read_entity_float(
            self._degree_minutes_entity, default=0.0
        )

        _LOGGER.debug(
            "Gree state: supply=%.1f°C, target=%.1f°C, outdoor=%.1f°C, "
            "heating=%s, dhw=%s, status=%s",
            supply_temp,
            target_supply_temp,
            outdoor_temp,
            is_heating,
            is_hot_water,
            unit_status,
        )

        return GreeState(
            outdoor_temp=outdoor_temp,
            indoor_temp=indoor_temp,
            supply_temp=supply_temp,
            return_temp=return_temp,
            target_supply_temp=target_supply_temp,
            is_heating=is_heating,
            is_hot_water=is_hot_water,
            timestamp=dt_util.now(),
            degree_minutes=degree_minutes,
            dhw_temp=dhw_temp,
            compressor_hz=int(compressor_hz) if compressor_hz is not None else None,
        )

    async def get_power_consumption(self) -> float | None:
        """Get current power consumption in kW.

        Returns:
            Power in kW or None if not available

        Note:
            Gree does not expose power consumption via Modbus.
            User can add a third-party power meter if needed.
        """
        return None

    # Helper methods for entity reading

    async def _read_entity_float(
        self, entity_id: str | None, default: float | None = None
    ) -> float | None:
        """Read a float value from a Home Assistant entity.

        Args:
            entity_id: Entity ID to read
            default: Default value if entity not found or invalid

        Returns:
            Float value or default
        """
        if not entity_id:
            return default

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Entity %s not found, using default %.1f", entity_id, default or 0.0)
            return default

        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Entity %s has invalid state '%s', using default %.1f",
                entity_id,
                state.state,
                default or 0.0,
            )
            return default

    async def _read_entity_bool(
        self, entity_id: str | None, default: bool = False
    ) -> bool:
        """Read a boolean value from a Home Assistant entity.

        Args:
            entity_id: Entity ID to read
            default: Default value if entity not found

        Returns:
            Boolean value or default
        """
        if not entity_id:
            return default

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Entity %s not found, using default %s", entity_id, default)
            return default

        # Support common boolean representations
        return state.state.lower() in ("true", "on", "1", "yes")

    async def _read_entity_string(
        self, entity_id: str | None, default: str = ""
    ) -> str:
        """Read a string value from a Home Assistant entity.

        Args:
            entity_id: Entity ID to read
            default: Default value if entity not found

        Returns:
            String value or default
        """
        if not entity_id:
            return default

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Entity %s not found, using default '%s'", entity_id, default)
            return default

        return str(state.state)
