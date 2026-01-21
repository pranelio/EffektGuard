"""Gree Versati 4 8kW heat pump profile via Modbus.

Gree Versati 4 is a mid-range inverter-based air source heat pump.
COP data extracted from manufacturer specifications at 30°C flow temperature.

Profile is based on:
- Gree Versati 4 GRS-CQ8.0PdG/NhH3-E specifications
- Measured COP curve at 30°C flow setpoint
- Gree Modbus integration capabilities
"""

from dataclasses import dataclass, field

from ...const import KUEHNE_COEFFICIENT, KUEHNE_POWER
from ..base import HeatPumpProfile, ValidationResult
from ..registry import HeatPumpModelRegistry


@HeatPumpModelRegistry.register("gree_versati4_8kw")
@dataclass
class GreeVersati48kwProfile(HeatPumpProfile):
    """Gree Versati 4 8kW Air Source Heat Pump (ASHP).

    **Model**: GRS-CQ8.0PdG/NhH3-E (Single-phase)
    **Target Market**: Residential heating systems with floor heating or radiators
    **Electrical**: Single-phase 220V or 3-phase available
    **Installation**: Modbus integration via Home Assistant

    **Power Characteristics**:
    - Rated heat output: 8kW (fixed, not variable across models)
    - Peak electrical input: 4kW at full load
    - Minimum electrical input: ~1kW at low modulation
    - Modulation: Inverter-based (0-100% compressor speed)

    **COP Performance** (at 30°C flow temperature setpoint):
    - Peak: 7.14 COP at 15°C outdoor (best case)
    - Good: 6.04 COP at 7°C outdoor (standard test)
    - Moderate: 3.6 COP at 0°C outdoor
    - Cold: 2.91 COP at -10°C outdoor
    - Extreme: 1.46 COP at -30°C outdoor

    **Thermal Debt Protection**: Uses Swedish-validated degree-minutes thresholds
    (validated across multiple heat pump types for safety)
    
    **Source**: Gree Versati 4 specifications, 30°C flow reference COP curve
    """

    # Identity
    model_name: str = "Versati IV 8kW"
    manufacturer: str = "Gree"
    model_type: str = "Single-Phase ASHP"

    rated_power_kw: tuple[float, float] = (8.0, 8.0)  # Fixed 8kW heat output
    typical_electrical_range_kw: tuple[float, float] = (1.0, 4.0)  # Min to peak power
    modulation_range: tuple[int, int] = (0, 100)  # 0-100% compressor speed
    modulation_type: str = "inverter"

    typical_cop_range: tuple[float, float] = (1.46, 7.14)  # From actual COP curve at 30°C flow
    optimal_flow_delta: float = 27.0  # SPF 3.5+ target
    cop_curve: dict[float, float] = field(default_factory=dict)

    supports_aux_heating: bool = False  # Gree Modbus typically doesn't expose this
    supports_modulation: bool = True 
    supports_weather_compensation: bool = False
    max_flow_temp: float = 55.0
    min_flow_temp: float = 20.0

    # Swedish optimization parameters (from NIBE research, applies universally)
    # These thresholds are validated across many heat pump types
    dm_threshold_start: float = -60  # Normal compressor start
    dm_threshold_extended: float = -240  # Extended runs acceptable
    dm_threshold_warning: float = -400  # Approaching thermal debt danger
    dm_threshold_critical: float = -500  # Emergency recovery needed
    dm_threshold_aux_swedish: float = -1500  # Auxiliary heat delay optimization

    min_runtime_minutes: int = 30
    min_rest_minutes: int = 10

    supports_exhaust_airflow: bool = False
    standard_airflow_m3h: float = 0.0
    enhanced_airflow_m3h: float = 0.0

    def __post_init__(self):
        """Initialize COP curve after dataclass creation."""
        self.cop_curve = {
            -30: 1.46,  
            -20: 2.07,  
            -10: 2.91,  
            0: 3.6, 
            5: 5.8,
            7: 6.04,
            10: 6.28,
            15: 7.14,
        }

    def calculate_optimal_flow_temp(
        self,
        outdoor_temp: float,
        indoor_target: float,
        heat_demand_kw: float,
    ) -> float:
        """Calculate optimal flow temperature using André Kühne formula.

        Conservative approach applied uniformly to all manufacturers.

        Args:
            outdoor_temp: Current outdoor temperature (°C)
            indoor_target: Target indoor temperature (°C)
            heat_demand_kw: Required heat output (kW)

        Returns:
            Optimal flow temperature (°C)
        """
        # André Kühne formula: TFlow = 2.55 × (HC × (Tset - Tout))^0.78 + Tset
        # Heat loss coefficient estimated from heat demand and temp delta
        # For Gree: assume ~0.3-0.5 kW per °C (conservative)
        heat_loss_coeff = min(heat_demand_kw / max(0.1, indoor_target - outdoor_temp), 250)

        # Apply Kühne formula
        temp_diff = indoor_target - outdoor_temp
        if temp_diff <= 0:
            return self.min_flow_temp

        exponent_term = (heat_loss_coeff * temp_diff) ** 0.78
        flow_temp = KUEHNE_COEFFICIENT * exponent_term + indoor_target

        # Constrain to system limits
        return max(self.min_flow_temp, min(flow_temp, self.max_flow_temp))

    def validate_power_consumption(
        self,
        current_power_kw: float,
        outdoor_temp: float,
        flow_temp: float,
    ) -> ValidationResult:
        """Validate if current power consumption is normal for Gree.

        Conservative validation to prevent over-heating.

        Args:
            current_power_kw: Current electrical power (kW)
            outdoor_temp: Current outdoor temperature (°C)
            flow_temp: Current flow temperature (°C)

        Returns:
            ValidationResult with severity and suggestions
        """
        # Get expected COP from curve
        expected_cop = self.cop_curve.get(
            round(outdoor_temp),
            self.typical_cop_range[0],  # Fallback to minimum
        )

        # Calculate expected heat output
        expected_heat_kw = current_power_kw * expected_cop

        # Check if within system limits
        if expected_heat_kw > self.rated_power_kw[1]:
            return ValidationResult(
                valid=False,
                severity="warning",
                message=f"Heat output {expected_heat_kw:.1f}kW exceeds rated {self.rated_power_kw[1]}kW",
                suggestions=[
                    "Check if auxiliary heater engaged",
                    "Verify flow temperature is not excessive",
                    "Consider thermal load analysis",
                ],
            )

        if current_power_kw > self.typical_electrical_range_kw[1]:
            return ValidationResult(
                valid=False,
                severity="warning",
                message=f"Power {current_power_kw:.1f}kW exceeds typical {self.typical_electrical_range_kw[1]}kW",
                suggestions=[
                    "Check for defrost cycle or auxiliary heater",
                    "Verify no second compressor active",
                    "Check electrical readings",
                ],
            )

        return ValidationResult(
            valid=True,
            severity="info",
            message=f"Power consumption normal: {current_power_kw:.1f}kW, COP ~{expected_cop:.1f}",
            suggestions=[],
        )
