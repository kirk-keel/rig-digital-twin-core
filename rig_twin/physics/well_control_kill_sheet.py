"""Automated Well Control Kill Sheet and Circulation Schedule Engine.

Computes Kill Mud Weight (KMW), Initial & Final Circulating Pressures (ICP/FCP),
MAASP, and circulation step-down pressure tables for the Wait & Weight and Driller's Methods.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class WellControlInput(BaseModel):
    """Input parameters measured upon shutting in the well on a kick."""
    well_id: str = "OFFSHORE-WELL"
    current_mud_weight_ppg: float = 11.2
    true_vertical_depth_ft: float = 11500.0
    measured_depth_ft: float = 11500.0
    casing_shoe_tvd_ft: float = 9500.0
    leak_off_test_emw_ppg: float = 14.8

    # Shut-in pressures
    shut_in_drillpipe_pressure_psi: float = 450.0  # SIDPP
    shut_in_casing_pressure_psi: float = 680.0     # SICP
    pit_gain_bbl: float = 18.5

    # Slow Circulating Rate (SCR) baseline (e.g. at 30 spm)
    slow_circulating_pressure_psi: float = 750.0   # P_scr
    pump_displacement_bbl_per_stroke: float = 0.119  # Triplex pump displacement


class KillSheetResult(BaseModel):
    """Output well control kill parameters and operational pressure schedules."""
    well_id: str
    current_mud_weight_ppg: float
    kill_mud_weight_ppg: float
    initial_circulating_pressure_psi: float  # ICP
    final_circulating_pressure_psi: float    # FCP
    
    # Well integrity limits
    initial_maasp_psi: float
    kill_maasp_psi: float
    influx_height_ft: float
    influx_gradient_psi_ft: float
    influx_type_estimate: str  # "GAS", "OIL", "SALT_WATER"

    # Volumetric and Stroke calculations
    surface_to_bit_volume_bbl: float
    surface_to_bit_strokes: int
    bit_to_shoe_volume_bbl: float
    bit_to_surface_volume_bbl: float
    bit_to_surface_strokes: int
    total_well_strokes: int

    # Pressure step-down schedule (Strokes vs Drill Pipe Pressure)
    step_down_schedule: List[Dict[str, float]]


class WellControlEngine:
    """Calculates API / IADC standard kill sheet parameters and step-down curves."""

    def __init__(self, inputs: WellControlInput):
        self.inputs = inputs

    def generate_kill_sheet(
        self,
        drillpipe_capacity_bbl_ft: float = 0.01776,  # 5" 19.5 lb/ft DP
        bha_capacity_bbl_ft: float = 0.00768,        # 6-1/2" Collars
        bha_length_ft: float = 600.0,
        annulus_open_hole_capacity_bbl_ft: float = 0.0459, # 8-1/2" hole x 5" DP
        annulus_casing_capacity_bbl_ft: float = 0.0489,    # 9-5/8" csg x 5" DP
    ) -> KillSheetResult:
        """Calculate complete well control kill sheet according to API RP 59 / IADC standards."""
        mw = self.inputs.current_mud_weight_ppg
        tvd = max(self.inputs.true_vertical_depth_ft, 100.0)
        shoe_tvd = max(self.inputs.casing_shoe_tvd_ft, 100.0)
        sidpp = self.inputs.shut_in_drillpipe_pressure_psi
        sicp = self.inputs.shut_in_casing_pressure_psi
        scr = self.inputs.slow_circulating_pressure_psi
        lot = self.inputs.leak_off_test_emw_ppg
        disp = max(self.inputs.pump_displacement_bbl_per_stroke, 0.01)

        # 1. Kill Mud Weight: KMW = MW + (SIDPP / (0.052 * TVD))
        kmw = mw + (sidpp / (0.052 * tvd))

        # 2. Initial Circulating Pressure: ICP = SIDPP + SCR
        icp = sidpp + scr

        # 3. Final Circulating Pressure: FCP = SCR * (KMW / MW)
        fcp = scr * (kmw / mw)

        # 4. Maximum Allowable Annular Surface Pressure (MAASP)
        initial_maasp = 0.052 * (lot - mw) * shoe_tvd
        kill_maasp = 0.052 * (lot - kmw) * shoe_tvd

        # 5. Influx Height & Type Determination
        # Height = Pit Gain / Annular Capacity around BHA or DP
        influx_h = self.inputs.pit_gain_bbl / max(annulus_open_hole_capacity_bbl_ft, 0.01)
        # Pressure balance: SICP - SIDPP = (rho_mud - rho_influx) * 0.052 * h_influx
        delta_p = sicp - sidpp
        if influx_h > 10.0 and delta_p > 0.0:
            influx_density_ppg = max(mw - (delta_p / (0.052 * influx_h)), 0.5)
            influx_gradient = 0.052 * influx_density_ppg
        else:
            influx_density_ppg = 2.0
            influx_gradient = 0.10

        if influx_gradient < 0.15:
            influx_type = "GAS"
        elif influx_gradient < 0.35:
            influx_type = "OIL / CONDENSATE"
        else:
            influx_type = "SALT_WATER"

        # 6. String Volumes and Pump Strokes
        dp_len = max(self.inputs.measured_depth_ft - bha_length_ft, 0.0)
        v_dp = dp_len * drillpipe_capacity_bbl_ft
        v_bha = bha_length_ft * bha_capacity_bbl_ft
        v_surf_bit = v_dp + v_bha
        strokes_surf_bit = int(math.ceil(v_surf_bit / disp))

        # Annular Volumes
        oh_len = max(self.inputs.measured_depth_ft - shoe_tvd, 0.0)
        csg_len = shoe_tvd
        v_bit_shoe = oh_len * annulus_open_hole_capacity_bbl_ft
        v_shoe_surf = csg_len * annulus_casing_capacity_bbl_ft
        v_bit_surf = v_bit_shoe + v_shoe_surf
        strokes_bit_surf = int(math.ceil(v_bit_surf / disp))
        total_strokes = strokes_surf_bit + strokes_bit_surf

        # 7. Step-Down Schedule: Pressure drops from ICP to FCP as kill mud travels surface -> bit
        steps = 10
        step_down = []
        d_stroke = strokes_surf_bit / steps
        d_press = (icp - fcp) / steps

        for i in range(steps + 1):
            stk = int(round(i * d_stroke))
            p_spp = round(icp - (i * d_press), 1)
            step_down.append({
                "strokes": stk,
                "drillpipe_pressure_psi": p_spp,
                "kill_mud_progress_pct": round((i / steps) * 100.0, 1),
            })

        return KillSheetResult(
            well_id=self.inputs.well_id,
            current_mud_weight_ppg=round(mw, 2),
            kill_mud_weight_ppg=round(kmw, 2),
            initial_circulating_pressure_psi=round(icp, 1),
            final_circulating_pressure_psi=round(fcp, 1),
            initial_maasp_psi=round(initial_maasp, 1),
            kill_maasp_psi=round(kill_maasp, 1),
            influx_height_ft=round(influx_h, 1),
            influx_gradient_psi_ft=round(influx_gradient, 3),
            influx_type_estimate=influx_type,
            surface_to_bit_volume_bbl=round(v_surf_bit, 1),
            surface_to_bit_strokes=strokes_surf_bit,
            bit_to_shoe_volume_bbl=round(v_bit_shoe, 1),
            bit_to_surface_volume_bbl=round(v_bit_surf, 1),
            bit_to_surface_strokes=strokes_bit_surf,
            total_well_strokes=total_strokes,
            step_down_schedule=step_down,
        )
