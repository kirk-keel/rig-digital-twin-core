"""Real-time Geopressure and Fracture Gradient Prediction (Eaton's & Matthews-Kelly formulations).

Computes corrected d-exponent (d_xc), Normal Compaction Trendlines (NCTL),
and predicts downhole pore pressure and fracture gradients dynamically from drilling telemetry.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel


class GeopressureProfilePoint(BaseModel):
    """Dynamic pore pressure and fracture gradient prediction at depth."""
    true_vertical_depth_ft: float
    d_exponent: float
    d_exponent_corrected: float
    normal_compaction_d_exp: float
    pore_pressure_psi: float
    pore_pressure_ppg: float
    fracture_gradient_psi: float
    fracture_gradient_ppg: float
    overburden_gradient_ppg: float
    is_overpressured: bool


class GeopressureEngine:
    """Predicts pore pressure and fracture gradient using Eaton's and Matthews-Kelly models."""

    def __init__(
        self,
        normal_pore_gradient_ppg: float = 8.65,  # 0.450 psi/ft normal water gradient
        overburden_gradient_ppg: float = 19.23,  # 1.0 psi/ft total rock stress
        poissons_ratio: float = 0.40,            # Typical shale Poisson's ratio (0.35 - 0.45)
        nctl_surface_d_exp: float = 1.00,
        nctl_slope_per_1000ft: float = 0.040,
    ):
        self.normal_pp_ppg = normal_pore_gradient_ppg
        self.overburden_ppg = overburden_gradient_ppg
        self.nu = poissons_ratio
        self.nctl_surface = nctl_surface_d_exp
        self.nctl_slope = nctl_slope_per_1000ft / 1000.0

    def calculate_d_exponent(
        self,
        rop_ft_hr: float,
        rpm: float,
        wob_klbf: float,
        bit_diameter_in: float,
        current_mud_weight_ppg: float,
    ) -> Tuple[float, float]:
        """Calculate Jorden & Shirley d-exponent and mud weight corrected d_xc.
        
        d = log10(ROP / (60 * RPM)) / log10(12 * WOB / (10^6 * D_bit))
        d_xc = d * (normal_mud_weight / actual_mud_weight)
        """
        if rop_ft_hr <= 0.1 or rpm <= 1.0 or wob_klbf <= 0.5:
            return 1.0, 1.0

        numerator = math.log10(max(rop_ft_hr / (60.0 * rpm), 1e-4))
        wob_term = (12.0 * wob_klbf * 1000.0) / (1e6 * bit_diameter_in)
        denominator = math.log10(max(wob_term, 1e-4))

        if abs(denominator) < 1e-5:
            d_raw = 1.0
        else:
            d_raw = numerator / denominator

        d_raw = max(min(d_raw, 3.5), 0.3)
        # Corrected d_xc for current mud density
        d_xc = d_raw * (self.normal_pp_ppg / max(current_mud_weight_ppg, 8.0))
        return round(d_raw, 3), round(d_xc, 3)

    def normal_compaction_trend(self, tvd_ft: float) -> float:
        """Normal Compaction Trendline (NCTL) expected d-exponent at depth.
        
        As shale compacts normally with burial depth, bulk density increases and
        rock matrix becomes harder, causing normal d-exponent to increase with depth.
        """
        val = self.nctl_surface + (self.nctl_slope * max(tvd_ft, 0.0))
        return max(val, 0.5)

    def predict_pressures(
        self,
        tvd_ft: float,
        rop_ft_hr: float,
        rpm: float,
        wob_klbf: float,
        bit_diameter_in: float,
        current_mud_weight_ppg: float,
    ) -> GeopressureProfilePoint:
        """Evaluate Eaton pore pressure and Matthews-Kelly fracture gradient."""
        d_raw, d_xc = self.calculate_d_exponent(
            rop_ft_hr=rop_ft_hr,
            rpm=rpm,
            wob_klbf=wob_klbf,
            bit_diameter_in=bit_diameter_in,
            current_mud_weight_ppg=current_mud_weight_ppg,
        )

        d_xcn = self.normal_compaction_trend(tvd_ft)
        ratio = max(min(d_xc / d_xcn, 1.5), 0.2)

        # Overburden and normal pore pressure in psi
        sigma_v = 0.052 * self.overburden_ppg * tvd_ft
        p_normal = 0.052 * self.normal_pp_ppg * tvd_ft

        # Eaton's equation: Pp = sigma_v - (sigma_v - Pn) * (d_xc / d_xcn)^1.2
        # In undercompacted/overpressured shale, d_xc drops below d_xcn, raising Pp
        if ratio < 1.0:
            pp_psi = sigma_v - (sigma_v - p_normal) * (ratio ** 1.2)
        else:
            pp_psi = p_normal

        # Bounds: Pp between normal and 95% of overburden
        pp_psi = max(min(pp_psi, sigma_v * 0.95), p_normal)
        pp_ppg = pp_psi / (0.052 * max(tvd_ft, 1.0))

        # Matthews-Kelly & Eaton Fracture Gradient:
        # Fg = (nu / (1 - nu)) * (sigma_v - Pp) + Pp
        k_ratio = self.nu / (1.0 - self.nu)
        frac_psi = k_ratio * (sigma_v - pp_psi) + pp_psi
        frac_ppg = frac_psi / (0.052 * max(tvd_ft, 1.0))

        is_overpressured = pp_ppg > (self.normal_pp_ppg + 0.75)

        return GeopressureProfilePoint(
            true_vertical_depth_ft=round(tvd_ft, 1),
            d_exponent=d_raw,
            d_exponent_corrected=d_xc,
            normal_compaction_d_exp=round(d_xcn, 3),
            pore_pressure_psi=round(pp_psi, 1),
            pore_pressure_ppg=round(pp_ppg, 2),
            fracture_gradient_psi=round(frac_psi, 1),
            fracture_gradient_ppg=round(frac_ppg, 2),
            overburden_gradient_ppg=round(self.overburden_ppg, 2),
            is_overpressured=is_overpressured,
        )
