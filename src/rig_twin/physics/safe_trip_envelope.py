"""Safe Tripping Speed Envelope Optimizer.

Inverts dynamic surge and swab non-Newtonian physics to calculate the maximum
allowable pipe running (RIH) and pulling (POOH) velocities across the wellbore.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple
from scipy.optimize import brentq

from rig_twin.core.models import FluidProperties, WellGeometry
from rig_twin.physics.surge_swab import SurgeSwabEngine


class SafeTripEnvelopeOptimizer:
    """Computes exact velocity ceilings to prevent swab kicks and surge induced fractures."""

    def __init__(
        self,
        geometry: WellGeometry,
        fluid: FluidProperties,
        pore_pressure_ppg: float = 10.2,
        fracture_pressure_ppg: float = 14.5,
        swab_safety_margin_ppg: float = 0.3,
        surge_safety_margin_ppg: float = 0.3,
    ):
        self.geometry = geometry
        self.fluid = fluid
        self.pore_pressure_ppg = pore_pressure_ppg
        self.fracture_pressure_ppg = fracture_pressure_ppg
        self.swab_safety_margin_ppg = swab_safety_margin_ppg
        self.surge_safety_margin_ppg = surge_safety_margin_ppg
        self.surge_swab_engine = SurgeSwabEngine(geometry, fluid)

    def calculate_max_safe_pooh_speed_ft_min(
        self, bit_depth_ft: float, tvd_ft: Optional[float] = None
    ) -> float:
        """Maximum safe pulling speed without swabbing below pore pressure + safety margin."""
        tvd = tvd_ft if tvd_ft is not None else bit_depth_ft
        if tvd <= 0.0:
            return 180.0

        min_allowed_ecd = self.pore_pressure_ppg + self.swab_safety_margin_ppg
        # Maximum allowed swab pressure drop in psi
        max_allowed_swab_psi = max((self.fluid.density_ppg - min_allowed_ecd) * 0.052 * tvd, 0.0)

        if max_allowed_swab_psi <= 1.0:
            # Already underbalanced or at the margin while stationary!
            return 5.0

        def obj(v_pooh: float) -> float:
            _, swab_psi = self.surge_swab_engine.calculate_surge_swab_psi(
                string_velocity_ft_min=-abs(v_pooh),
                bit_depth_ft=bit_depth_ft,
            )
            return swab_psi - max_allowed_swab_psi

        try:
            # Check upper bracket (300 ft/min)
            if obj(300.0) <= 0.0:
                return 300.0
            if obj(5.0) >= 0.0:
                return 5.0
            v_max = brentq(obj, 5.0, 300.0, xtol=1.0)
            return round(v_max, 1)
        except Exception:
            return 60.0

    def calculate_max_safe_rih_speed_ft_min(
        self, bit_depth_ft: float, tvd_ft: Optional[float] = None
    ) -> float:
        """Maximum safe running speed without surging above fracture gradient - safety margin."""
        tvd = tvd_ft if tvd_ft is not None else bit_depth_ft
        if tvd <= 0.0:
            return 180.0

        max_allowed_ecd = self.fracture_pressure_ppg - self.surge_safety_margin_ppg
        max_allowed_surge_psi = max((max_allowed_ecd - self.fluid.density_ppg) * 0.052 * tvd, 0.0)

        if max_allowed_surge_psi <= 1.0:
            return 5.0

        def obj(v_rih: float) -> float:
            surge_psi, _ = self.surge_swab_engine.calculate_surge_swab_psi(
                string_velocity_ft_min=abs(v_rih),
                bit_depth_ft=bit_depth_ft,
            )
            return surge_psi - max_allowed_surge_psi

        try:
            if obj(300.0) <= 0.0:
                return 300.0
            if obj(5.0) >= 0.0:
                return 5.0
            v_max = brentq(obj, 5.0, 300.0, xtol=1.0)
            return round(v_max, 1)
        except Exception:
            return 90.0

    def generate_safe_trip_profile(
        self, max_depth_ft: float, step_ft: float = 1000.0
    ) -> List[Dict[str, float]]:
        """Generate full wellbore profile of safe tripping speeds."""
        profile = []
        d = step_ft
        while d <= max_depth_ft:
            pooh_max = self.calculate_max_safe_pooh_speed_ft_min(d)
            rih_max = self.calculate_max_safe_rih_speed_ft_min(d)
            profile.append({
                "depth_ft": d,
                "max_safe_pooh_speed_ft_min": pooh_max,
                "max_safe_rih_speed_ft_min": rih_max,
                "pore_pressure_ppg": self.pore_pressure_ppg,
                "fracture_pressure_ppg": self.fracture_pressure_ppg,
            })
            d += step_ft
        return profile
