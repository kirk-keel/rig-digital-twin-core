"""Wellbore hydraulics engine for computing frictional pressure drops, ECD, and SPP."""

from __future__ import annotations

import math
from typing import Dict, List, Tuple
from rig_twin.core.models import (
    BitGeometry,
    DrillStringSection,
    FluidProperties,
    TubularSection,
    WellGeometry,
)
from rig_twin.physics.rheology import RheologyEngine


class HydraulicsEngine:
    """Computes downhole pressures, dynamic frictional losses, bit hydraulics, and ECD."""

    def __init__(self, geometry: WellGeometry, fluid: FluidProperties):
        self.geometry = geometry
        self.fluid = fluid
        self.rheology = RheologyEngine(fluid)

    def hydrostatic_pressure_psi(self, tvd_ft: float) -> float:
        """Hydrostatic pressure at specified TVD: P = 0.052 * rho[ppg] * TVD[ft]."""
        return 0.052 * self.fluid.density_ppg * max(tvd_ft, 0.0)

    def bit_pressure_loss_psi(
        self, flow_rate_gpm: float, bit: BitGeometry, discharge_coeff: float = 0.95
    ) -> Tuple[float, float, float, float]:
        """Compute bit nozzle pressure drop, nozzle velocity, HHP, and impact force.
        
        Returns:
            (delta_p_psi, jet_velocity_fps, hydraulic_hp, impact_force_lbf)
        """
        if flow_rate_gpm <= 0.0:
            return 0.0, 0.0, 0.0, 0.0

        tfa = bit.total_flow_area_sq_in
        if tfa <= 0.001:
            raise ValueError(f"Invalid Bit TFA: {tfa} sq in")

        rho = self.fluid.density_ppg
        # API equation: delta_P = (rho * Q^2) / (10858 * Cd^2 * TFA^2)
        delta_p = (rho * (flow_rate_gpm ** 2)) / (10858.0 * (discharge_coeff ** 2) * (tfa ** 2))

        # Jet velocity: v_n = Q / (3.117 * TFA) [ft/s]
        v_jet = flow_rate_gpm / (3.117 * tfa)

        # Bit Hydraulic Horsepower: HHP = (delta_p * Q) / 1714
        hhp = (delta_p * flow_rate_gpm) / 1714.0

        # Jet impact force: F_imp = 0.01823 * Cd * Q * sqrt(rho * delta_p)
        impact_force = 0.01823 * discharge_coeff * flow_rate_gpm * math.sqrt(max(rho * delta_p, 0.0))

        return delta_p, v_jet, hhp, impact_force

    def surface_equipment_loss_psi(self, flow_rate_gpm: float, equipment_class: int = 3) -> float:
        """Pressure drop through surface equipment (standpipe, hose, swivel, top drive).
        
        API formulation: dP = C * 10^-5 * rho * Q^1.86
        where C is between 1 (large bore / short line) and 4 (standard/restricted).
        """
        if flow_rate_gpm <= 0.0:
            return 0.0
        c_factor = {1: 1.0, 2: 1.8, 3: 2.5, 4: 4.2}.get(equipment_class, 2.5)
        return (c_factor * 1e-5) * self.fluid.density_ppg * (flow_rate_gpm ** 1.86)

    def pipe_internal_losses_psi(
        self, flow_rate_gpm: float, bit_depth_ft: float
    ) -> Tuple[float, List[Dict[str, float]]]:
        """Compute frictional pressure loss inside drillstring elements down to bit_depth."""
        if flow_rate_gpm <= 0.0:
            return 0.0, []

        total_loss = 0.0
        section_results = []
        depth_covered = 0.0

        for section in self.geometry.drillstring_sections:
            if depth_covered >= bit_depth_ft:
                break

            # Active length of this section inside the well
            active_length = min(section.length_ft, bit_depth_ft - depth_covered)
            if active_length <= 0:
                continue

            # Velocity in pipe: v = Q / (2.448 * ID^2) [ft/s]
            id_sq = section.inner_diameter_in ** 2
            v_fps = flow_rate_gpm / (2.448 * id_sq)

            re, regime = self.rheology.pipe_reynolds_number(v_fps, section.inner_diameter_in)
            f = self.rheology.fanning_friction_factor(re, regime, is_annulus=False)

            # API frictional loss: dP = (f * rho * v^2 * L) / (25.8 * ID) [psi]
            dp = (f * self.fluid.density_ppg * (v_fps ** 2) * active_length) / (
                25.8 * section.inner_diameter_in
            )

            total_loss += dp
            section_results.append({
                "section": section.name,
                "length_ft": active_length,
                "velocity_fps": v_fps,
                "reynolds": re,
                "regime": regime,
                "friction_factor": f,
                "dp_psi": dp,
            })
            depth_covered += active_length

        return total_loss, section_results

    def _discretize_annulus(
        self, bit_depth_ft: float
    ) -> List[Tuple[float, float, float, float, float]]:
        """Discretize the wellbore into intervals with uniform (hole_id, pipe_od).
        
        Returns list of tuples: (top_depth, bottom_depth, hole_id, pipe_od, friction_mult)
        """
        # Collect boundary depths
        boundaries = {0.0, bit_depth_ft}
        for c in self.geometry.casing_sections:
            if c.top_depth_ft < bit_depth_ft:
                boundaries.add(min(c.top_depth_ft, bit_depth_ft))
            if c.bottom_depth_ft < bit_depth_ft:
                boundaries.add(min(c.bottom_depth_ft, bit_depth_ft))

        # Drillstring depth boundaries
        cum_len = 0.0
        for s in self.geometry.drillstring_sections:
            cum_len += s.length_ft
            if cum_len < bit_depth_ft:
                boundaries.add(cum_len)

        sorted_depths = sorted(list(boundaries))
        intervals = []

        for i in range(len(sorted_depths) - 1):
            top_d = sorted_depths[i]
            bot_d = sorted_depths[i + 1]
            if bot_d <= top_d:
                continue
            mid_d = 0.5 * (top_d + bot_d)

            # Find hole diameter and roughness multiplier at mid_d
            hole_id = 8.5
            f_mult = 1.0
            for c in self.geometry.casing_sections:
                if c.top_depth_ft <= mid_d <= c.bottom_depth_ft:
                    hole_id = c.inner_diameter_in
                    f_mult = c.friction_factor_multiplier
                    break

            # Find pipe outer diameter at mid_d
            pipe_od = 5.0
            pipe_d_cum = 0.0
            for s in self.geometry.drillstring_sections:
                if pipe_d_cum <= mid_d <= (pipe_d_cum + s.length_ft):
                    pipe_od = s.outer_diameter_in
                    break
                pipe_d_cum += s.length_ft

            intervals.append((top_d, bot_d, hole_id, pipe_od, f_mult))

        return intervals

    def annular_pressure_loss_psi(
        self, flow_rate_gpm: float, bit_depth_ft: float
    ) -> Tuple[float, List[Dict[str, float]], str]:
        """Calculate total annular pressure loss (APL) along wellbore from bit to surface."""
        if flow_rate_gpm <= 0.0 or bit_depth_ft <= 0.0:
            return 0.0, [], "LAMINAR"

        intervals = self._discretize_annulus(bit_depth_ft)
        total_apl = 0.0
        interval_details = []
        predominant_regimes = []

        for top_d, bot_d, hole_id, pipe_od, f_mult in intervals:
            length = bot_d - top_d
            hyd_diam = max(hole_id - pipe_od, 0.05)
            area_equiv = max(hole_id ** 2 - pipe_od ** 2, 0.1)

            # Annular velocity: v_ann = Q / (2.448 * (Dh^2 - Dp^2)) [ft/s]
            v_ann = flow_rate_gpm / (2.448 * area_equiv)

            re, regime = self.rheology.annular_reynolds_number(v_ann, hole_id, pipe_od)
            f = self.rheology.fanning_friction_factor(re, regime, is_annulus=True) * f_mult

            # Annular pressure loss: dP = (f * rho * v^2 * L) / (25.8 * (Dh - Dp)) [psi]
            dp = (f * self.fluid.density_ppg * (v_ann ** 2) * length) / (25.8 * hyd_diam)

            total_apl += dp
            predominant_regimes.append(regime)
            interval_details.append({
                "top_ft": top_d,
                "bottom_ft": bot_d,
                "hole_id": hole_id,
                "pipe_od": pipe_od,
                "velocity_fps": v_ann,
                "reynolds": re,
                "regime": regime,
                "dp_psi": dp,
            })

        # Predominant regime
        turb_count = sum(1 for r in predominant_regimes if r == "TURBULENT")
        overall_regime = "TURBULENT" if turb_count > len(predominant_regimes) // 2 else "LAMINAR"

        return total_apl, interval_details, overall_regime

    def equivalent_circulating_density_ppg(
        self, annular_loss_psi: float, tvd_ft: float
    ) -> float:
        """Compute Equivalent Circulating Density (ECD) in ppg.
        
        ECD = rho_mud + (APL / (0.052 * TVD))
        """
        if tvd_ft <= 0.0:
            return self.fluid.density_ppg
        return self.fluid.density_ppg + (annular_loss_psi / (0.052 * tvd_ft))
