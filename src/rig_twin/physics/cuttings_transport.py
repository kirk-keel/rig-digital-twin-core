"""Cuttings transport, particle slip velocity, and annular bed dynamics.

Implements Larsen and Moore hole cleaning formulations to evaluate
settling velocity, bed accumulation, and the real-time Hole Cleaning Index (HCI).
"""

from __future__ import annotations

import math
from typing import Dict
from rig_twin.core.models import FluidProperties


class CuttingsTransportEngine:
    """Evaluates annular cuttings concentration, bed height, and Hole Cleaning Index."""

    def __init__(
        self,
        fluid: FluidProperties,
        cuttings_density_ppg: float = 21.7,  # Sandstone / shale grain density (~2.6 g/cm³)
        cuttings_diameter_in: float = 0.125, # 1/8 inch median cuttings size
    ):
        self.fluid = fluid
        self.cuttings_density_ppg = cuttings_density_ppg
        self.cuttings_diameter_in = cuttings_diameter_in

    def particle_slip_velocity_fps(self, apparent_viscosity_cp: float) -> float:
        """Chien & Moore non-Newtonian particle settling slip velocity in ft/s."""
        d_p_ft = self.cuttings_diameter_in / 12.0
        delta_rho = max(self.cuttings_density_ppg - self.fluid.density_ppg, 1.0)
        mu_cp = max(apparent_viscosity_cp, 1.0)

        # Chien correlation: vs = 0.0075 * (mu/rho) * (sqrt(1 + 36800 * d_p * delta_rho / (mu^2 / rho)) - 1)
        term1 = mu_cp / self.fluid.density_ppg
        term2 = (36800.0 * d_p_ft * delta_rho) / (term1 ** 2)
        v_slip = 0.0075 * term1 * (math.sqrt(1.0 + term2) - 1.0)
        return min(max(v_slip, 0.05), 3.5)

    def critical_transport_velocity_fps(
        self, inclination_deg: float, apparent_viscosity_cp: float
    ) -> float:
        """Larsen's critical velocity to prevent stationary cuttings bed formation.
        
        Account for steep angles (30-60 deg) having highest critical velocity due to avalanche effect.
        """
        inc_factor = 1.0 + 0.8 * math.sin(2.0 * math.radians(min(inclination_deg, 90.0)))
        # Base critical velocity: scales with (delta_rho / rho)^0.67
        density_ratio = max(self.cuttings_density_ppg - self.fluid.density_ppg, 1.0) / self.fluid.density_ppg
        v_crit_base = 1.2 * (density_ratio ** 0.6) * ((self.cuttings_diameter_in / 0.1) ** 0.35)
        # Viscosity dampening
        visc_factor = (30.0 / max(apparent_viscosity_cp, 10.0)) ** 0.2
        return v_crit_base * inc_factor * visc_factor

    def evaluate_hole_cleaning(
        self,
        annular_velocity_fps: float,
        rate_of_penetration_ft_hr: float,
        hole_diameter_in: float,
        pipe_od_in: float,
        inclination_deg: float = 0.0,
        apparent_viscosity_cp: float = 35.0,
    ) -> Dict[str, float]:
        """Compute transport ratio, bed height fraction, friction multiplier, and Hole Cleaning Index (HCI)."""
        v_slip = self.particle_slip_velocity_fps(apparent_viscosity_cp)
        v_crit = self.critical_transport_velocity_fps(inclination_deg, apparent_viscosity_cp)

        # Transport Ratio: Tr = 1 - (v_slip / v_ann)
        if annular_velocity_fps > 0.01:
            transport_ratio = max(1.0 - (v_slip / annular_velocity_fps), 0.0)
            hci = annular_velocity_fps / v_crit
        else:
            transport_ratio = 0.0
            hci = 0.0

        # Cuttings volumetric generation rate
        annulus_area_sq_in = math.pi * 0.25 * (hole_diameter_in ** 2 - pipe_od_in ** 2)
        hole_area_sq_in = math.pi * 0.25 * (hole_diameter_in ** 2)
        q_cuttings_cfs = (rate_of_penetration_ft_hr / 3600.0) * (hole_area_sq_in / 144.0)

        # In-situ volumetric cuttings concentration
        v_ann_safe = max(annular_velocity_fps, 0.1)
        c_annulus = q_cuttings_cfs / ((annulus_area_sq_in / 144.0) * v_ann_safe * max(transport_ratio, 0.1))
        c_annulus = min(max(c_annulus, 0.0), 0.40)

        # Bed height estimation: if HCI < 1.0, bed builds up
        bed_fraction = max(0.0, (1.0 - hci) * 0.35) if hci < 1.0 else 0.0

        # Annular hydraulic friction factor multiplier due to cuttings presence
        friction_multiplier = 1.0 + (2.5 * c_annulus) + (1.8 * bed_fraction)

        return {
            "hole_cleaning_index": round(hci, 2),
            "transport_ratio": round(transport_ratio, 3),
            "particle_slip_velocity_fps": round(v_slip, 2),
            "critical_velocity_fps": round(v_crit, 2),
            "cuttings_concentration_pct": round(c_annulus * 100.0, 2),
            "cuttings_bed_fraction": round(bed_fraction, 3),
            "annular_friction_multiplier": round(friction_multiplier, 3),
        }
