"""Gree heat pump model profiles.

Gree is a Chinese manufacturer of heat pumps and air conditioning units.

Supported models:
- Versati 4 (8kW): Mid-range inverter heat pump, via Modbus integration
"""

from .versati4_8kw import GreeVersati48kwProfile

__all__ = [
    "GreeVersati48kwProfile",
]
