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
    CONF_GREE_WEATHER_DEPEND_ENTITY,
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
    supply_temp: float  
    return_temp: float | None
    target_supply_temp: float  
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
        self._weather_depend_entity = config.get(CONF_GREE_WEATHER_DEPEND_ENTITY)
        self._last_supply_temp: float | None = None  # Cache for setpoint calculations
        self._last_write: datetime | None = None  # Rate limiting

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

        # Cache supply temp for setpoint calculations
        self._last_supply_temp = supply_temp

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

    async def set_supply_temp_target(
        self, offset: float, min_temp: float = 20.0, max_temp: float = 60.0
    ) -> bool:
        """Set target supply temperature via HA entity (offset-based control).

        Unlike NIBE which accepts curve offsets, Gree requires absolute temperatures
        (1°C increments). This method converts the offset to an absolute target by
        combining with the current measured supply temperature.

        Decision engine offset range: -10.0 to +10.0°C
        Applied as: target = round(current_supply_temp + offset)

        Prerequisites:
        - Weather compensation (weather depend switch) must be disabled.
          If user has enabled it between calls, we detect and disable it.

        Args:
            offset: Optimization offset from decision engine (-10 to +10°C)
            min_temp: Minimum allowed supply temp (default 20°C)
            max_temp: Maximum allowed supply temp (default 60°C, lower for UFH)

        Returns:
            True if setpoint was written to Gree, False if skipped/failed

        Note:
            For UFH systems, caller should set max_temp ~35°C.
            For radiator systems, max_temp can be 55-60°C.
            Setup-specific max_temp should come from model profile or config.

        Example:
            # Current supply is 32°C, decision says +1.5°C for savings
            success = await adapter.set_supply_temp_target(
                offset=1.5,
                min_temp=20,
                max_temp=35  # UFH system
            )
            # Result: Gree gets setpoint of 34°C (round(32 + 1.5))
        """
        from datetime import timedelta

        # Rate limiting - don't thrash Gree with constant writes
        now = dt_util.now()
        if self._last_write and now - self._last_write < timedelta(minutes=2):
            _LOGGER.debug("Skipping supply temp write, too soon since last write")
            return False

        # Current supply temperature (from last read_state call)
        if not hasattr(self, "_last_supply_temp"):
            _LOGGER.error("Supply temperature not yet available, skipping setpoint")
            return False

        current_supply = self._last_supply_temp

        # Calculate absolute target temperature
        target_temp = current_supply + offset
        target_temp_int = round(target_temp)  # Gree only accepts 1°C increments

        # Clamp to valid range
        target_temp_int = max(min_temp, min(target_temp_int, max_temp))

        _LOGGER.debug(
            "Supply temp calculation: current=%.1f°C, offset=%.2f°C, "
            "target=%.1f°C → rounded=%d°C (clamped: %d-%d°C)",
            current_supply,
            offset,
            target_temp,
            target_temp_int,
            min_temp,
            max_temp,
        )

        # Step 1: Check if weather depend is enabled (should never be for setpoint control)
        weather_depend_entity = self._get_weather_depend_entity()
        if not weather_depend_entity:
            _LOGGER.warning(
                "Weather depend switch entity not configured, cannot safely set supply temp"
            )
            return False

        weather_depend_state = self.hass.states.get(weather_depend_entity)
        if weather_depend_state and weather_depend_state.state == "on":
            # Weather compensation is enabled - must disable it first
            _LOGGER.warning(
                "Weather depend is enabled, disabling to allow setpoint control"
            )
            success = await self._disable_weather_depend(weather_depend_entity)
            if not success:
                _LOGGER.error("Failed to disable weather depend, aborting setpoint write")
                return False

        # Step 2: Write target supply temperature to Gree
        supply_temp_entity = self._get_supply_temp_setpoint_entity()
        if not supply_temp_entity:
            _LOGGER.error("Supply temp setpoint entity not configured")
            return False

        try:
            await self.hass.services.async_call(
                "number",
                "set_value",
                {
                    "entity_id": supply_temp_entity,
                    "value": target_temp_int,
                },
                blocking=False,
            )
            self._last_write = now
            self._last_supply_temp = target_temp_int  # Update tracking

            _LOGGER.info(
                "✓ Applied supply temp to Gree: %.1f°C → %d°C (offset: %.2f°C)",
                current_supply,
                target_temp_int,
                offset,
            )
            return True

        except (AttributeError, OSError, ValueError, TypeError) as err:
            _LOGGER.error("Failed to set Gree supply temp: %s", err)
            return False

    def _get_weather_depend_entity(self) -> str | None:
        """Get weather depend (weather compensation) switch entity ID.

        Returns:
            Entity ID or None if not configured
        """
        return self._weather_depend_entity

    def _get_supply_temp_setpoint_entity(self) -> str | None:
        """Get supply temperature setpoint (target) entity ID.

        Returns:
            Entity ID or None if not configured
        """
        return self._target_supply_temp_entity

    async def _disable_weather_depend(self, entity_id: str) -> bool:
        """Disable weather depend switch to allow manual supply temp control.

        Args:
            entity_id: Switch entity for weather compensation

        Returns:
            True if disabled, False if failed
        """
        try:
            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": entity_id},
                blocking=False,
            )
            _LOGGER.info("✓ Disabled weather depend to allow supply temp setpoint")
            return True
        except (AttributeError, OSError) as err:
            _LOGGER.error("Failed to disable weather depend: %s", err)
            return False

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
