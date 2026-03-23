"""Analysis type registry, base classes, and unit conversion system."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional, Type

import numpy as np


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UnitDefinition:
    """A unit with conversion factors relative to its quantity's base unit."""
    name: str           # Display name, e.g. "g"
    symbol: str         # Short symbol used as key, e.g. "g"
    base_quantity: str  # Physical quantity, e.g. "acceleration"
    to_base: float      # Multiply raw value by this to get base-unit value
    from_base: float    # Multiply base-unit value by this to get this unit


class UnitConverter:
    """Centralised unit conversion engine.

    Every physical quantity has a *base unit*.  Conversions always go
    ``source -> base -> target``.
    """

    _units: ClassVar[Dict[str, Dict[str, UnitDefinition]]] = {}
    _bootstrapped: ClassVar[bool] = False

    # ------------------------------------------------------------------
    @classmethod
    def _ensure_bootstrapped(cls) -> None:
        if cls._bootstrapped:
            return
        cls._bootstrapped = True
        G = 9.80665
        DEG2RAD = np.pi / 180.0

        # Acceleration  (base: m/s^2)
        cls._reg("acceleration", "m/s\u00b2", 1.0)
        cls._reg("acceleration", "g",        G, 1.0 / G)
        cls._reg("acceleration", "mm/s\u00b2", 1e-3, 1e3)
        cls._reg("acceleration", "in/s\u00b2", 0.0254, 1.0 / 0.0254)

        # Angular velocity  (base: rad/s)
        cls._reg("angular_velocity", "rad/s", 1.0)
        cls._reg("angular_velocity", "dps",   DEG2RAD, 1.0 / DEG2RAD)
        cls._reg("angular_velocity", "rpm",   np.pi / 30.0, 30.0 / np.pi)

        # Frequency  (base: Hz)
        cls._reg("frequency", "Hz",  1.0)
        cls._reg("frequency", "kHz", 1e3, 1e-3)

        # Time  (base: s)
        cls._reg("time", "s",  1.0)
        cls._reg("time", "ms", 1e-3, 1e3)
        cls._reg("time", "\u00b5s", 1e-6, 1e6)

        # Velocity  (base: m/s)
        cls._reg("velocity", "m/s",  1.0)
        cls._reg("velocity", "mm/s", 1e-3, 1e3)
        cls._reg("velocity", "in/s", 0.0254, 1.0 / 0.0254)

        # Displacement  (base: m)
        cls._reg("displacement", "m",   1.0)
        cls._reg("displacement", "mm",  1e-3, 1e3)
        cls._reg("displacement", "in",  0.0254, 1.0 / 0.0254)
        cls._reg("displacement", "mil", 2.54e-5, 1.0 / 2.54e-5)

        # Dimensionless / dB  (passthrough)
        cls._reg("dimensionless", "",   1.0)
        cls._reg("amplitude_dB",  "dB", 1.0)

    @classmethod
    def _reg(cls, quantity: str, symbol: str,
             to_base: float, from_base: float | None = None) -> None:
        if from_base is None:
            from_base = 1.0 / to_base if to_base != 0 else 1.0
        unit = UnitDefinition(
            name=symbol, symbol=symbol,
            base_quantity=quantity,
            to_base=to_base, from_base=from_base,
        )
        cls._units.setdefault(quantity, {})[symbol] = unit

    # ------------------------------------------------------------------
    @classmethod
    def convert(cls, values: np.ndarray,
                from_unit: str, to_unit: str,
                quantity: str) -> np.ndarray:
        """Convert *values* between two units of the same quantity."""
        cls._ensure_bootstrapped()
        if from_unit == to_unit:
            return values
        q = cls._units.get(quantity, {})
        src = q.get(from_unit)
        dst = q.get(to_unit)
        if src is None or dst is None:
            return values  # unknown unit — return unchanged
        return values * src.to_base * dst.from_base

    @classmethod
    def get_units_for_quantity(cls, quantity: str) -> List[str]:
        """Return list of unit symbols available for *quantity*."""
        cls._ensure_bootstrapped()
        return list(cls._units.get(quantity, {}).keys())


# ---------------------------------------------------------------------------
# Axis / result containers
# ---------------------------------------------------------------------------

@dataclass
class AxisConfig:
    """Metadata for one axis of a plot."""
    label: str              # e.g. "Frequency"
    quantity: str           # ties into UnitConverter, e.g. "frequency"
    default_unit: str       # e.g. "Hz"
    log_scale_default: bool = False


@dataclass
class AnalysisResult:
    """Standard result container returned by every analysis ``compute()``."""
    x_data: Dict[str, np.ndarray]   # channel -> x values
    y_data: Dict[str, np.ndarray]   # channel -> y values
    x_axis: AxisConfig
    y_axis: AxisConfig
    metadata: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base class and registry
# ---------------------------------------------------------------------------

class BaseAnalysis(ABC):
    """Abstract base for all analysis types."""

    name: str = ""
    category: str = ""
    description: str = ""

    @abstractmethod
    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str]) -> AnalysisResult:
        """Run the analysis on selected *channels*."""
        ...


class AnalysisRegistry:
    """Singleton registry of available analysis types."""

    _analyses: ClassVar[Dict[str, BaseAnalysis]] = {}
    _categories: ClassVar[Dict[str, List[str]]] = {}

    @classmethod
    def register(cls, analysis_class: Type[BaseAnalysis]) -> Type[BaseAnalysis]:
        """Class decorator (or direct call) to register an analysis type."""
        instance = analysis_class()
        key = f"{instance.category}/{instance.name}"
        cls._analyses[key] = instance
        cat_list = cls._categories.setdefault(instance.category, [])
        if instance.name not in cat_list:
            cat_list.append(instance.name)
        return analysis_class

    @classmethod
    def get(cls, category: str, name: str) -> Optional[BaseAnalysis]:
        return cls._analyses.get(f"{category}/{name}")

    @classmethod
    def get_categories(cls) -> Dict[str, List[str]]:
        """Return ``{category: [analysis_names]}``."""
        return dict(cls._categories)
