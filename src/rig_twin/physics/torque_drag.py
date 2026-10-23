"""Torque & Drag (T&D) modeling using the 3D Soft-String Johancsik formulation.

Predicts hook load envelopes (pick-up, slack-off, rotating off-bottom),
evaluates borehole friction factors, and calculates buckling limits.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
from rig_twin.core.models import DrillStringSection, FluidProperties, WellGeometry


class TorqueDragEngine:
    """Johancsik soft-string torque and drag calculator with buckling thresholds."""

    def __init__(self, geometry: WellGeometry, fluid: FluidProperties):
        self.geometry = geometry
        self.fluid = fluid
        # Steel density: 65.4 ppg (489.5 lb/ft^3)
        self.steel_density_ppg = 65.4
        # Young's Modulus for drilling steel: 30 x 10^6 psi
        self.youngs_modulus_psi = 30e6

    @property
    def buoyancy_factor(self) -> float:
        """Buoyancy factor: BF = 1 - (rho_mud / rho_steel)."""
        return max(1.0 - (self.fluid.density_ppg / self.steel_density_ppg), 0.5)

    def _approximate_section_weight_lb_per_ft(self, s: DrillStringSection) -> float:
        """Weight in air per foot of pipe: 2.67 * (OD^2 - ID^2) lb/ft."""
        return 2.67 * (s.outer_diameter_in ** 2 - s.inner_diameter_in ** 2)

    def calculate_hookload_and_torque(
        self,
        bit_depth_ft: float,
        friction_coeff: float = 0.25,
        wob_klbf: float = 0.0,
        bit_torque_ft_lbf: float = 0.0,
        average_inclination_deg: float = 15.0,
        dogleg_deg_per_100ft: float = 1.5,
    ) -> Dict[str, float]:
        """Calculate hook loads and surface torque for pick-up, slack-off, and rotating states.
        
        Returns dict with:
        - pickup_hookload_klbf
        - slackoff_hookload_klbf
        - rotating_hookload_klbf
        - surface_torque_ft_lbf
        - sinusoidal_buckling_limit_klbf
        - helical_buckling_limit_klbf
        """
        bf = self.buoyancy_factor
        inc_rad = math.radians(average_inclination_deg)
        dl_rad_per_ft = math.radians(dogleg_deg_per_100ft) / 100.0

        # Boundary condition at bit
        # During drilling: WOB is in compression (+ in standard WOB, negative axial tension)
        t_pickup = wob_klbf * 1000.0
        t_slackoff = -wob_klbf * 1000.0
        t_rotating = 0.0
        surf_torque = bit_torque_ft_lbf

        # Discretize drillstring from bit to surface
        cum_depth = 0.0
        first_section_od = 5.0
        first_section_id = 4.276

        for s in reversed(self.geometry.drillstring_sections):
            active_len = min(s.length_ft, max(bit_depth_ft - cum_depth, 0.0))
            if active_len <= 0.0:
                continue

            first_section_od = s.outer_diameter_in
            first_section_id = s.inner_diameter_in

            w_air = self._approximate_section_weight_lb_per_ft(s)
            w_buoyed = w_air * bf

            # Step through length intervals
            dz = 30.0  # 30 ft segments
            n_segments = max(int(active_len / dz), 1)
            seg_len = active_len / n_segments

            for _ in range(n_segments):
                delta_alpha = dl_rad_per_ft * seg_len
                w_seg = w_buoyed * seg_len

                # Normal contact force: Fn = sqrt((T * delta_alpha)^2 + (w * sin(inc))^2)
                fn_pickup = math.sqrt((t_pickup * delta_alpha) ** 2 + (w_seg * math.sin(inc_rad)) ** 2)
                fn_slackoff = math.sqrt((t_slackoff * delta_alpha) ** 2 + (w_seg * math.sin(inc_rad)) ** 2)
                fn_rotating = math.sqrt((t_rotating * delta_alpha) ** 2 + (w_seg * math.sin(inc_rad)) ** 2)

                f_drag_pickup = friction_coeff * fn_pickup
                f_drag_slackoff = friction_coeff * fn_slackoff

                # Axial load integration
                t_pickup += (w_seg * math.cos(inc_rad)) + f_drag_pickup
                t_slackoff += (w_seg * math.cos(inc_rad)) - f_drag_slackoff
                t_rotating += (w_seg * math.cos(inc_rad))

                # Torque integration: dT = mu * Fn * (OD / 24) [ft-lbf]
                surf_torque += friction_coeff * fn_rotating * (s.outer_diameter_in / 24.0)

            cum_depth += active_len

        # Buckling load limits on lower section (Dawson-Paslay & Chen-Cheatham)
        # Moment of Inertia: I = pi/64 * (OD^4 - ID^4)
        moment_of_inertia = (math.pi / 64.0) * (first_section_od ** 4 - first_section_id ** 4)
        radial_clearance_in = max(8.5 - first_section_od, 0.5)
        w_sub = self._approximate_section_weight_lb_per_ft(self.geometry.drillstring_sections[0]) * bf / 12.0

        sin_inc = max(math.sin(inc_rad), 0.05)
        stiffness_term = self.youngs_modulus_psi * moment_of_inertia * w_sub * sin_inc / radial_clearance_in
        f_sin_buckling_lbf = 2.0 * math.sqrt(max(stiffness_term, 1.0))
        f_hel_buckling_lbf = 2.83 * math.sqrt(max(stiffness_term, 1.0))

        # Traveling block / top drive weight offset (~65 klbf)
        block_weight_klbf = 65.0

        return {
            "pickup_hookload_klbf": round((t_pickup / 1000.0) + block_weight_klbf, 1),
            "slackoff_hookload_klbf": round((t_slackoff / 1000.0) + block_weight_klbf, 1),
            "rotating_hookload_klbf": round((t_rotating / 1000.0) + block_weight_klbf, 1),
            "surface_torque_ft_lbf": round(surf_torque, 1),
            "sinusoidal_buckling_limit_klbf": round(f_sin_buckling_lbf / 1000.0, 1),
            "helical_buckling_limit_klbf": round(f_hel_buckling_lbf / 1000.0, 1),
        }

    def generate_broomstick_envelope(
        self,
        max_depth_ft: float,
        friction_coeffs: List[float] = [0.15, 0.25, 0.35],
        step_ft: float = 500.0,
    ) -> List[Dict[str, float]]:
        """Generate comprehensive Broomstick curves for hook load vs depth."""
        envelope = []
        d = step_ft
        while d <= max_depth_ft:
            row = {"depth_ft": d}
            for mu in friction_coeffs:
                res = self.calculate_hookload_and_torque(bit_depth_ft=d, friction_coeff=mu)
                row[f"pickup_mu_{mu}"] = res["pickup_hookload_klbf"]
                row[f"slackoff_mu_{mu}"] = res["slackoff_hookload_klbf"]
                row[f"rotating_mu_{mu}"] = res["rotating_hookload_klbf"]
            envelope.append(row)
            d += step_ft
        return envelope
