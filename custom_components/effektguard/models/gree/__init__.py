"""Gree heat pump model profiles.

Gree is a Chinese manufacturer of heat pumps and air conditioning units.
Gree heat pumps connected via Modbus are typically mid-range systems.

Supported models:
- Generic Gree: Universal profile for Gree heat pumps via Modbus
"""

from .generic import GreeGenericProfile

__all__ = [
    "GreeGenericProfile",
]
