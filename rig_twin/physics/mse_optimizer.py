"""Mechanical Specific Energy (MSE) tracking, drilling efficiency, and vibration detection."""

from __future__ import annotations

import math
from typing import Dict, Optional


class MSEDrillingOptimizer:
    """Computes Teale's Mechanical Specific Energy and diagnoses drilling dysfunctions."""

    def __init__(self, bit_diameter_in: float = 8.5):
        self.bit_diameter_in = bit_diameter_in
        self.bit_area_sq_in = math.pi * 0.25 * (bit_diameter_in ** 2)

    def compute_mse_psi(
        self,
        wob_klbf: float,
        surface_torque_ft_lbf: float,
        surface_rpm: float,
        rate_of_penetration_ft_hr: float,
    ) -> float:
        """Calculate Teale's Mechanical Specific Energy in psi.
        
        MSE = (WOB / A_bit) + (120 * pi * RPM * Torque) / (A_bit * ROP)
        """
        if rate_of_penetration_ft_hr <= 0.1 or self.bit_area_sq_in <= 0.0:
            return 1e6  # Off-bottom or zero penetration

        wob_lbf = max(wob_klbf * 1000.0, 0.0)
        torque = max(surface_torque_ft_lbf, 0.0)
        rpm = max(surface_rpm, 0.0)
        rop = rate_of_penetration_ft_hr

        # Axial thrust component
        term_axial = wob_lbf / self.bit_area_sq_in

        # Rotary torsional component
        term_rotary = (120.0 * math.pi * rpm * torque) / (self.bit_area_sq_in * rop)

        return term_axial + term_rotary

    def diagnose_drilling_state(
        self,
        wob_klbf: float,
        surface_torque_ft_lbf: float,
        surface_rpm: float,
        rate_of_penetration_ft_hr: float,
        rock_strength_ccs_psi: float = 18000.0,
        torque_std_dev: float = 350.0,
    ) -> Dict[str, float | str | bool]:
        """Evaluate mechanical efficiency and flag bit balling or stick-slip vibration."""
        mse = self.compute_mse_psi(wob_klbf, surface_torque_ft_lbf, surface_rpm, rate_of_penetration_ft_hr)
        
        # Mechanical efficiency: Eff = Rock Strength / MSE
        mechanical_efficiency = min(max(rock_strength_ccs_psi / max(mse, 1.0), 0.0), 1.0)

        # Dysfunction indicators
        is_bit_balling = False
        is_stick_slip = False
        recommendation = "Maintain current drilling parameters."

        # Bit balling: high WOB (> 25 klbf), low ROP (< 15 ft/hr), low efficiency (< 20%)
        if wob_klbf > 25.0 and rate_of_penetration_ft_hr < 15.0 and mechanical_efficiency < 0.20:
            is_bit_balling = True
            recommendation = "Bit balling detected: Increase flow rate, pick up off bottom, spin bit to clear cutters."

        # Stick-slip: high torque variation relative to mean (> 35%)
        if surface_torque_ft_lbf > 1000.0 and (torque_std_dev / surface_torque_ft_lbf) > 0.35:
            is_stick_slip = True
            recommendation = "Severe stick-slip vibration detected: Increase surface RPM and slightly reduce WOB."

        return {
            "mse_psi": round(mse, 1),
            "mechanical_efficiency_pct": round(mechanical_efficiency * 100.0, 1),
            "is_bit_balling": is_bit_balling,
            "is_stick_slip": is_stick_slip,
            "recommendation": recommendation,
        }
