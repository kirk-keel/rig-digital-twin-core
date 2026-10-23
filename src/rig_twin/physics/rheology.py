"""Petroleum non-Newtonian fluid rheology models and wall shear rate calculations.

Implements Herschel-Bulkley (Yield-Power-Law), Bingham-Plastic, and Power-Law
rheological constitutive equations according to API RP 13D standards.
"""

from __future__ import annotations

import math
from typing import Tuple
import numpy as np
from rig_twin.core.models import FluidProperties, RheologyModelType


class RheologyEngine:
    """Computes shear rates, shear stresses, effective viscosities, and friction factors."""

    def __init__(self, fluid: FluidProperties):
        self.fluid = fluid

    def shear_stress(self, shear_rate_s1: float) -> float:
        """Compute shear stress in lbf/100 ft² for a given shear rate (1/s)."""
        gamma = max(abs(shear_rate_s1), 1e-4)

        if self.fluid.model_type == RheologyModelType.NEWTONIAN:
            # Newtonian: tau = mu * gamma. PV in cP to lbf*s/100ft² is ~ pv * 0.0020885
            return 0.0020885 * self.fluid.pv_cp * gamma

        elif self.fluid.model_type == RheologyModelType.BINGHAM_PLASTIC:
            # tau = YP + PV * gamma * 0.0020885
            return self.fluid.yp_lbf_100sqft + (0.0020885 * self.fluid.pv_cp * gamma)

        elif self.fluid.model_type == RheologyModelType.POWER_LAW:
            # tau = K * gamma^n
            return self.fluid.k_consistency * (gamma ** self.fluid.n_flow_index)

        elif self.fluid.model_type == RheologyModelType.HERSCHEL_BULKLEY:
            # tau = tau_0 + K * gamma^n
            return self.fluid.yield_stress_lbf_100sqft + (
                self.fluid.k_consistency * (gamma ** self.fluid.n_flow_index)
            )

        raise ValueError(f"Unsupported rheology model {self.fluid.model_type}")

    def apparent_viscosity_cp(self, shear_rate_s1: float) -> float:
        """Calculate apparent viscosity in centipoise (cP) at a given shear rate."""
        gamma = max(abs(shear_rate_s1), 1e-4)
        tau_lbf_100sqft = self.shear_stress(gamma)
        # 1 lbf/100ft² / (1/s) = 478.8 cP
        return (tau_lbf_100sqft / gamma) * 478.8

    def pipe_shear_rate(self, mean_velocity_fps: float, inner_diameter_in: float) -> float:
        """Wall shear rate inside circular pipe (API RP 13D formulation).
        
        gamma_w = ((3n + 1) / 4n) * (8 * v / d)
        """
        d_ft = inner_diameter_in / 12.0
        n = self.fluid.n_flow_index
        factor = (3.0 * n + 1.0) / (4.0 * n)
        return factor * (8.0 * abs(mean_velocity_fps) / d_ft)

    def annular_shear_rate(
        self, mean_velocity_fps: float, hole_diameter_in: float, pipe_od_in: float
    ) -> float:
        """Annular wall shear rate between concentric cylinders (API RP 13D).
        
        gamma_w = ((2n + 1) / 3n) * (12 * v / (d_h - d_p))
        """
        hyd_diam_ft = (hole_diameter_in - pipe_od_in) / 12.0
        hyd_diam_ft = max(hyd_diam_ft, 0.001)
        n = self.fluid.n_flow_index
        factor = (2.0 * n + 1.0) / (3.0 * n)
        return factor * (12.0 * abs(mean_velocity_fps) / hyd_diam_ft)

    def pipe_reynolds_number(
        self, mean_velocity_fps: float, inner_diameter_in: float
    ) -> Tuple[float, str]:
        """Compute Generalized Reynolds Number (Reg) and flow regime for pipe flow."""
        v = abs(mean_velocity_fps)
        if v < 1e-6:
            return 0.0, "LAMINAR"

        gamma = self.pipe_shear_rate(v, inner_diameter_in)
        mu_eff_cp = self.apparent_viscosity_cp(gamma)
        rho_ppg = self.fluid.density_ppg

        # Reynolds number in field units: Re = 928 * rho[ppg] * v[ft/s] * d[in] / mu[cP]
        re = (928.0 * rho_ppg * v * inner_diameter_in) / max(mu_eff_cp, 0.1)

        # Non-Newtonian critical Reynolds number via Hanks/API 13D criterion
        re_crit = 2100.0 * (self.fluid.n_flow_index ** 0.5)

        if re < re_crit:
            regime = "LAMINAR"
        elif re < re_crit + 800.0:
            regime = "TRANSITIONAL"
        else:
            regime = "TURBULENT"

        return re, regime

    def annular_reynolds_number(
        self, mean_velocity_fps: float, hole_diameter_in: float, pipe_od_in: float
    ) -> Tuple[float, str]:
        """Compute Generalized Reynolds Number (Reg) and flow regime for annular flow."""
        v = abs(mean_velocity_fps)
        if v < 1e-6:
            return 0.0, "LAMINAR"

        hyd_diam_in = max(hole_diameter_in - pipe_od_in, 0.01)
        gamma = self.annular_shear_rate(v, hole_diameter_in, pipe_od_in)
        mu_eff_cp = self.apparent_viscosity_cp(gamma)
        rho_ppg = self.fluid.density_ppg

        # Annular field units: Re = 757 * rho[ppg] * v[ft/s] * (Dh - Dp)[in] / mu[cP]
        re = (757.0 * rho_ppg * v * hyd_diam_in) / max(mu_eff_cp, 0.1)

        re_crit = 2100.0 * (self.fluid.n_flow_index ** 0.5)
        if re < re_crit:
            regime = "LAMINAR"
        elif re < re_crit + 800.0:
            regime = "TRANSITIONAL"
        else:
            regime = "TURBULENT"

        return re, regime

    def fanning_friction_factor(self, re: float, regime: str, is_annulus: bool = False) -> float:
        """Compute Fanning friction factor f based on Reynolds number and flow regime."""
        if re <= 1e-6:
            return 0.0

        if regime == "LAMINAR":
            # In pipe: f = 16 / Re; In narrow slot annulus: f = 24 / Re
            return (24.0 if is_annulus else 16.0) / max(re, 1.0)
        elif regime == "TRANSITIONAL":
            # Smooth cubic spline interpolation across transition zone
            n = self.fluid.n_flow_index
            re_crit = 2100.0 * (n ** 0.5)
            f_lam = (24.0 if is_annulus else 16.0) / re_crit
            # Dodge-Metzner turbulent baseline at upper transition
            re_turb = re_crit + 800.0
            f_turb = 0.0791 / (re_turb ** 0.25)
            t = (re - re_crit) / 800.0
            t = min(max(t, 0.0), 1.0)
            return (1.0 - t) * f_lam + t * f_turb
        else:
            # Dodge-Metzner correlation for non-Newtonian turbulent flow:
            # f ≈ a / (Re_g)^b where a ≈ 0.0791 * n^0.67, b ≈ 0.25
            n = self.fluid.n_flow_index
            return (0.0791 * (n ** 0.67)) / (re ** 0.25)
