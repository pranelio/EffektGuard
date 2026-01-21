"""Generic Gree heat pump profile via Modbus.

Gree systems via Modbus typically lack detailed specifications,
so we use conservative, well-tested Swedish NIBE values that work
across many heat pump types.

Profile is based on:
- NIBE Swedish research (validated in real conditions)
- Gree Modbus integration capabilities
- Assumption of well-matched mid-range systems (5-12kW range)
"""

from dataclasses import dataclass, field

from ...const import KUEHNE_COEFFICIENT, KUEHNE_POWER
from ..base import HeatPumpProfile, ValidationResult
from ..registry import HeatPumpModelRegistry


@HeatPumpModelRegistry.register("gree_versati4_8kw")
@dataclass
class GreeVersati48kwProfile(HeatPumpProfile):
    """Gree Versati 4 - 8kW Model.

    **Target Market**: Mid-range Gree systems (5-12kW) connected via Modbus
    **Typical Application**: Floor heating, radiators, mixed systems
    **Electrical**: Varies by model, typically 3-phase 16-20A

    **Power Characteristics**:
    - Assumed range: 5-12kW heat output
    - Modulation: Depends on inverter type
    - Typical: 2-4kW electrical for well-matched system

    **COP Performance** (from Swedish NIBE research, applied conservatively):
    - Best: 4.0 at 7°C outdoor
    - Good: 3.5 at 0°C
    - Acceptable: 2.5 at -10°C
    - Survival: 1.8 at -25°C

    **Note**: Since Gree does not expose detailed specifications via Modbus,
    we use validated Swedish NIBE thresholds that work across most heat pump types.
    This conservative approach ensures safety and prevents thermal debt accumulation.

    **Source**: Swedish NIBE forum validation, Gree Modbus integration patterns
    """

    # Identity
    model_name: str = "Generic Gree"
    manufacturer: str = "Gree"
    model_type: str = "Modbus ASHP/GSHP"

    # Power characteristics (conservative mid-range estimate)
    rated_power_kw: tuple[float, float] = (5.0, 12.0)  # Heat output range
    typical_electrical_range_kw: tuple[float, float] = (1.5, 5.0)  # Estimated
    modulation_range: tuple[int, int] = (0, 100)  # % (inverter likely)
    modulation_type: str = "inverter"

    # Efficiency - Conservative from Swedish NIBE research
    # Applied to Gree since detailed specs unavailable via Modbus
    typical_cop_range: tuple[float, float] = (1.8, 4.0)
    optimal_flow_delta: float = 27.0  # SPF 3.5+ target
    cop_curve: dict[float, float] = field(default_factory=dict)

    # System capabilities (assumed from Modbus integration)
    supports_aux_heating: bool = False  # Gree Modbus typically doesn't expose this
    supports_modulation: bool = True  # Most Gree systems have inverters
    supports_weather_compensation: bool = False  # Not via standard Modbus
    max_flow_temp: float = 55.0
    min_flow_temp: float = 20.0

    # Swedish optimization parameters (from NIBE research, applies universally)
    # These thresholds are validated across many heat pump types
    dm_threshold_start: float = -60  # Normal compressor start
    dm_threshold_extended: float = -240  # Extended runs acceptable
    dm_threshold_warning: float = -400  # Approaching thermal debt danger
    dm_threshold_critical: float = -500  # Emergency recovery needed
    dm_threshold_aux_swedish: float = -1500  # Auxiliary heat delay optimization

    # Cycling protection (standard across heat pump types)
    min_runtime_minutes: int = 30
    min_rest_minutes: int = 10

    # Gree via Modbus doesn't expose exhaust airflow optimization
    supports_exhaust_airflow: bool = False
    standard_airflow_m3h: float = 0.0
    enhanced_airflow_m3h: float = 0.0

    def __post_init__(self):
        """Initialize COP curve after dataclass creation."""
        # Conservative COP curve from Swedish NIBE research
        # Applied to Gree since manufacturer specs unavailable via Modbus
        self.cop_curve = {
            -30: 1.8,  # Extreme cold - survival mode
            -20: 2.0,  # Deep freeze (Kiruna)
            -10: 2.5,  # Cold (Stockholm winter)
            0: 3.5,  # Moderate cold (Malmö/Gothenburg average)
            5: 3.8,  # Mild cold
            7: 4.0,  # Optimal mild (Swedish standard test)
            10: 3.9,  # Just above freezing
            15: 3.5,  # Spring/Fall
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
