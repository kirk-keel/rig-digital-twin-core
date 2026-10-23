"""Dynamic surge and swab pressure computation during drillstring motion.

Implements Burkhardt and Lubinski non-Newtonian tripping physics to predict
bottomhole pressure fluctuations during pipe movement (RIH / POOH).
"""

from __future__ import annotations

import math
from typing import List, Tuple
from rig_twin.core.models import FluidProperties, WellGeometry
from rig_twin.physics.rheology import RheologyEngine


class SurgeSwabEngine:
    """Calculates surge (pressure increase during RIH) and swab (pressure drop during POOH)."""

    def __init__(self, geometry: WellGeometry, fluid: FluidProperties):
        self.geometry = geometry
        self.fluid = fluid
        self.rheology = RheologyEngine(fluid)

    def clinging_constant(self, hole_diam_in: float, pipe_od_in: float) -> float:
        """Burkhardt / Lubinski clinging factor Kc for mud dragged with moving pipe.
        
        Represents the fraction of fluid boundary layer carried along with the pipe.
        Typical values range from 0.35 to 0.50 for drilling geometries.
        """
        if hole_diam_in <= pipe_od_in:
            return 0.5
        ratio = pipe_od_in / hole_diam_in
        n = self.fluid.n_flow_index

        # Theoretical boundary layer integration for power-law annular drag
        # Lubinski non-Newtonian approximation
        kc_approx = (1.0 - ratio ** 2) / (2.0 * math.log(max(1.0 / ratio, 1.001))) - (ratio ** 2)
        kc_corrected = kc_approx * (0.8 + 0.2 * n)
        return min(max(kc_corrected, 0.25), 0.55)

    def effective_tripping_velocity_fps(
        self,
        pipe_velocity_fps: float,
        hole_diam_in: float,
        pipe_od_in: float,
        pipe_id_in: float,
        is_float_closed: bool = True,
    ) -> float:
        """Calculate effective annular fluid displacement velocity due to pipe movement.
        
        Args:
            pipe_velocity_fps: Absolute pipe movement velocity in ft/s.
            hole_diam_in: Outer wellbore / casing ID.
            pipe_od_in: Pipe outer diameter.
            pipe_id_in: Pipe inner diameter.
            is_float_closed: True if bit float valve is closed (or plugged bit).
        """
        kc = self.clinging_constant(hole_diam_in, pipe_od_in)
        dh_sq = hole_diam_in ** 2
        dp_sq = pipe_od_in ** 2

        annulus_area_factor = max(dh_sq - dp_sq, 0.05)

        if is_float_closed:
            # Closed end: Entire displacement of pipe OD travels up annulus
            disp_ratio = dp_sq / annulus_area_factor
        else:
            # Open end: Fluid enters pipe bore; only steel cross-sectional displacement
            di_sq = pipe_id_in ** 2
            disp_ratio = max(dp_sq - di_sq, 0.01) / annulus_area_factor

        # v_eff = v_pipe * (disp_ratio + Kc)
        return abs(pipe_velocity_fps) * (disp_ratio + kc)

    def calculate_surge_swab_psi(
        self,
        string_velocity_ft_min: float,
        bit_depth_ft: float,
        is_float_closed: bool = True,
    ) -> Tuple[float, float]:
        """Compute surge pressure (if RIH) and swab pressure (if POOH) in psi.
        
        Args:
            string_velocity_ft_min: Pipe velocity (ft/min). Positive = RIH, Negative = POOH.
            bit_depth_ft: Current bit depth in feet.
            is_float_closed: Whether drillstring is closed at bit.
            
        Returns:
            (surge_pressure_psi, swab_pressure_psi)
        """
        if abs(string_velocity_ft_min) < 1e-3 or bit_depth_ft <= 0.0:
            return 0.0, 0.0

        v_pipe_fps = abs(string_velocity_ft_min) / 60.0

        # Discretize along wellbore intervals
        from rig_twin.physics.hydraulics import HydraulicsEngine
        hydraulics = HydraulicsEngine(self.geometry, self.fluid)
        intervals = hydraulics._discretize_annulus(bit_depth_ft)

        total_dynamic_dp = 0.0

        # Estimate average pipe ID for intervals
        default_pipe_id = 4.276
        if self.geometry.drillstring_sections:
            default_pipe_id = self.geometry.drillstring_sections[0].inner_diameter_in

        for top_d, bot_d, hole_id, pipe_od, f_mult in intervals:
            length = bot_d - top_d
            hyd_diam = max(hole_id - pipe_od, 0.05)

            v_eff = self.effective_tripping_velocity_fps(
                pipe_velocity_fps=v_pipe_fps,
                hole_diam_in=hole_id,
                pipe_od_in=pipe_od,
                pipe_id_in=default_pipe_id,
                is_float_closed=is_float_closed,
            )

            re, regime = self.rheology.annular_reynolds_number(v_eff, hole_id, pipe_od)
            f = self.rheology.fanning_friction_factor(re, regime, is_annulus=True) * f_mult

            # Pressure loss = (f * rho * v^2 * L) / (25.8 * (Dh - Dp))
            dp_interval = (f * self.fluid.density_ppg * (v_eff ** 2) * length) / (25.8 * hyd_diam)
            total_dynamic_dp += dp_interval

        # Inertial / acceleration safety margin factor (~1.1 for unsteady acceleration peaks)
        unsteady_factor = 1.15
        dynamic_pressure = total_dynamic_dp * unsteady_factor

        if string_velocity_ft_min > 0:
            # Tripping in -> Surge pressure increases bottomhole pressure
            return dynamic_pressure, 0.0
        else:
            # Tripping out -> Swab pressure reduces bottomhole pressure
            return 0.0, dynamic_pressure
