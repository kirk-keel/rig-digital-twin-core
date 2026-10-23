"""Casing Wear & Drillpipe Cyclic Metal Fatigue Accumulator.

Implements the White & Dawson / Maurer casing wear model and Palmgren-Miner
cyclic bending fatigue tracking in directional wellbore doglegs.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel


class CasingWearSectionResult(BaseModel):
    """Casing wear depth, remaining wall thickness, and derated burst/collapse limits."""
    casing_name: str
    depth_ft: float
    dogleg_severity_deg_100ft: float
    contact_force_lbf: float
    rotating_hours: float
    wear_groove_depth_in: float
    nominal_wall_thickness_in: float
    remaining_wall_thickness_in: float
    wall_loss_pct: float
    nominal_burst_psi: float
    derated_burst_psi: float
    nominal_collapse_psi: float
    derated_collapse_psi: float
    is_casing_integrity_compromised: bool


class DrillpipeFatigueResult(BaseModel):
    """Palmgren-Miner cyclic bending fatigue damage on drillpipe joints."""
    measured_depth_ft: float
    dogleg_severity_deg_100ft: float
    bending_stress_psi: float
    endurance_limit_psi: float
    cycles_accumulated: int
    cycles_to_failure: int
    fatigue_damage_index: float  # Palmgren-Miner index: 0.0 -> 1.0 (failure)
    is_fatigue_limit_threatened: bool


class CasingWearAndFatigueEngine:
    """Evaluates mechanical wear on casing strings and cumulative fatigue on rotating drillpipe."""

    def __init__(
        self,
        casing_nominal_od_in: float = 9.625,
        casing_nominal_wall_in: float = 0.472,  # 9-5/8" 47# casing
        casing_nominal_burst_psi: float = 6870.0,
        casing_nominal_collapse_psi: float = 4760.0,
        tooljoint_od_in: float = 6.625,
        mud_sand_content_pct: float = 0.5,
        steel_youngs_modulus_psi: float = 30e6,
    ):
        self.csg_od = casing_nominal_od_in
        self.csg_wall = casing_nominal_wall_in
        self.burst_nom = casing_nominal_burst_psi
        self.collapse_nom = casing_nominal_collapse_psi
        self.tj_od = tooljoint_od_in
        self.sand_pct = mud_sand_content_pct
        self.e_psi = steel_youngs_modulus_psi

        # Specific wear factor Wf: ~1.5e-10 psi^-1 baseline, amplified by abrasiveness/sand
        self.wf_base = 1.5e-10 * (1.0 + 0.4 * max(mud_sand_content_pct, 0.0))

    def calculate_casing_wear(
        self,
        depth_ft: float,
        contact_force_lbf: float,
        dogleg_deg_100ft: float,
        rotating_hours: float,
        rpm: float = 120.0,
        casing_name: str = "9-5/8 Intermediate Casing",
    ) -> CasingWearSectionResult:
        """White & Dawson casing wear groove penetration and burst/collapse derating."""
        # Sliding distance in inches: S = pi * D_tj * RPM * (hours * 60)
        sliding_dist_in = math.pi * self.tj_od * rpm * (max(rotating_hours, 0.01) * 60.0)

        # Contact force amplified in high doglegs: Fn_eff
        fn = max(contact_force_lbf, 10.0)

        # Wear volume per inch: V_w = W_f * Fn * S
        v_wear = self.wf_base * fn * sliding_dist_in

        # Maurer crescent groove depth approximation: h_w ≈ sqrt(V_w / (0.8 * D_tj))
        wear_depth = math.sqrt(v_wear / (0.8 * self.tj_od))
        wear_depth = min(wear_depth, self.csg_wall * 0.95)  # Physical ceiling

        remaining_wall = max(self.csg_wall - wear_depth, 0.01)
        wall_loss_pct = (wear_depth / self.csg_wall) * 100.0

        # Derate burst linearly with remaining wall: P_b = P_b0 * (t_rem / t_nom)
        derated_burst = self.burst_nom * (remaining_wall / self.csg_wall)

        # Derate collapse quadratically with remaining wall: P_c = P_c0 * (t_rem / t_nom)^2.2
        derated_collapse = self.collapse_nom * ((remaining_wall / self.csg_wall) ** 2.2)

        # Compromised if > 25% wall loss or burst derated below 4500 psi
        is_compromised = wall_loss_pct > 25.0 or derated_burst < 4500.0

        return CasingWearSectionResult(
            casing_name=casing_name,
            depth_ft=depth_ft,
            dogleg_severity_deg_100ft=dogleg_deg_100ft,
            contact_force_lbf=round(fn, 1),
            rotating_hours=round(rotating_hours, 1),
            wear_groove_depth_in=round(wear_depth, 4),
            nominal_wall_thickness_in=round(self.csg_wall, 4),
            remaining_wall_thickness_in=round(remaining_wall, 4),
            wall_loss_pct=round(wall_loss_pct, 1),
            nominal_burst_psi=round(self.burst_nom, 1),
            derated_burst_psi=round(derated_burst, 1),
            nominal_collapse_psi=round(self.collapse_nom, 1),
            derated_collapse_psi=round(derated_collapse, 1),
            is_casing_integrity_compromised=is_compromised,
        )

    def calculate_drillpipe_fatigue(
        self,
        depth_ft: float,
        dogleg_deg_100ft: float,
        rotating_hours: float,
        pipe_od_in: float = 5.0,
        rpm: float = 120.0,
        steel_grade_yield_psi: float = 135000.0,  # S-135 drillpipe
    ) -> DrillpipeFatigueResult:
        """Palmgren-Miner cyclic bending fatigue damage accumulation in doglegs."""
        # Bending radius in feet: R = 5729.6 / DLS
        dls = max(dogleg_deg_100ft, 0.05)
        radius_ft = 5729.58 / dls

        # Cyclic alternating bending stress: sigma_b = (E * D_pipe / 2) / (12 * R)
        sigma_b_psi = (self.e_psi * (pipe_od_in / 12.0) / 2.0) / radius_ft

        # Endurance limit (~40% of yield strength for S-135)
        endurance_limit = steel_grade_yield_psi * 0.40

        # Accumulated rotation cycles
        cycles = int(rpm * 60.0 * max(rotating_hours, 0.01))

        if sigma_b_psi <= endurance_limit:
            # Below fatigue limit: infinite life
            n_failure = 10000000
            fatigue_damage = min(cycles / n_failure, 0.05)
        else:
            # Basquin S-N curve: N_f = A * (sigma_b)^-m where m ≈ 4.8
            ratio = endurance_limit / sigma_b_psi
            n_failure = max(int(1e6 * (ratio ** 4.8)), 1000)
            fatigue_damage = min(max(cycles / n_failure, 0.0), 1.0)

        is_threatened = fatigue_damage > 0.75

        return DrillpipeFatigueResult(
            measured_depth_ft=depth_ft,
            dogleg_severity_deg_100ft=dls,
            bending_stress_psi=round(sigma_b_psi, 1),
            endurance_limit_psi=round(endurance_limit, 1),
            cycles_accumulated=cycles,
            cycles_to_failure=n_failure,
            fatigue_damage_index=round(fatigue_damage, 4),
            is_fatigue_limit_threatened=is_threatened,
        )
