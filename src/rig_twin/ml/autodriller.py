"""Autonomous Drilling Advisory & Setpoint Optimizer (Auto-Driller).

Continuously computes closed-loop setpoint recommendations [WOB, RPM, Flow]
to maximize Rate of Penetration (ROP) while eliminating stick-slip, bit balling,
and honoring wellbore ECD geopressure margins.
"""

from __future__ import annotations

import math
from typing import Dict, Optional
from pydantic import BaseModel, Field

from rig_twin.core.models import PhysicsBaseline, TelemetryRecord


class AutoDrillerSetpointRecommendation(BaseModel):
    """Recommended drilling operating setpoints and engineering rationale."""
    recommended_wob_klbf: float = Field(..., description="Recommended Weight on Bit in klbf")
    recommended_rpm: float = Field(..., description="Recommended rotary table / top drive RPM")
    recommended_flow_rate_gpm: float = Field(..., description="Recommended mud pump circulation rate")
    expected_rop_ft_hr: float
    expected_mse_psi: float
    optimization_strategy: str
    is_setpoint_adjusted: bool
    diagnostic_rationale: str
    constraints_active: Dict[str, bool] = Field(default_factory=dict)


class AutoDrillerAdvisory:
    """Evaluates real-time drilling telemetry, MSE, and ECD bounds to recommend optimal setpoints."""

    def __init__(
        self,
        max_rig_spp_psi: float = 4800.0,
        max_topdrive_torque_ft_lbf: float = 24000.0,
        max_wob_klbf: float = 45.0,
        min_wob_klbf: float = 8.0,
        max_rpm: float = 180.0,
        min_rpm: float = 50.0,
        target_rock_ccs_psi: float = 18000.0,
    ):
        self.max_spp = max_rig_spp_psi
        self.max_torque = max_topdrive_torque_ft_lbf
        self.max_wob = max_wob_klbf
        self.min_wob = min_wob_klbf
        self.max_rpm = max_rpm
        self.min_rpm = min_rpm
        self.rock_ccs = target_rock_ccs_psi

    def evaluate_setpoints(
        self,
        telemetry: TelemetryRecord,
        physics: PhysicsBaseline,
        rate_of_penetration_ft_hr: float = 65.0,
        current_wob_klbf: float = 20.0,
        pore_pressure_ppg: float = 10.6,
        fracture_pressure_ppg: float = 14.5,
        torque_std_dev: float = 400.0,
    ) -> AutoDrillerSetpointRecommendation:
        """Analyze current state and output optimized [WOB, RPM, Flow Rate] setpoints."""
        curr_wob = max(min(current_wob_klbf, self.max_wob), self.min_wob)
        curr_rpm = max(min(telemetry.surface_rpm if telemetry.surface_rpm > 10 else 120.0, self.max_rpm), self.min_rpm)
        curr_flow = max(telemetry.flow_rate_in_gpm if telemetry.flow_rate_in_gpm > 50 else 520.0, 100.0)

        bit_area = math.pi * 0.25 * (8.5 ** 2)
        # Instantaneous MSE
        term_axial = (curr_wob * 1000.0) / bit_area
        term_rotary = (120.0 * math.pi * curr_rpm * max(telemetry.surface_torque_ft_lbf, 1000.0)) / (bit_area * max(rate_of_penetration_ft_hr, 1.0))
        mse_current = term_axial + term_rotary

        rec_wob = curr_wob
        rec_rpm = curr_rpm
        rec_flow = curr_flow
        strategy = "STEADY_DRILLING"
        rationale = "Current drilling parameters operate efficiently near target Mechanical Specific Energy."
        adjusted = False
        constraints = {
            "spp_limit_active": False,
            "ecd_margin_active": False,
            "torque_limit_active": False,
            "stick_slip_active": False,
            "bit_balling_active": False,
        }

        # 1. Hydraulic & Geopressure Protection: ECD and SPP bounds
        ecd_upper_bound = fracture_pressure_ppg - 0.40
        if physics.dynamic_ecd_ppg > ecd_upper_bound:
            rec_flow = max(curr_flow - 35.0, 380.0)
            strategy = "MANAGE_ECD_PRESSURE_WINDOW"
            rationale = (
                f"Dynamic ECD ({physics.dynamic_ecd_ppg:.2f} ppg) is approaching fracture margin "
                f"({fracture_pressure_ppg:.2f} ppg). Reduced pump rate to {rec_flow:.0f} gpm to lower annular pressure loss."
            )
            adjusted = True
            constraints["ecd_margin_active"] = True

        elif physics.total_predicted_spp_psi > (self.max_spp - 200.0):
            rec_flow = max(curr_flow - 25.0, 380.0)
            strategy = "MANAGE_SPP_PRESSURE"
            rationale = f"Standpipe pressure ({physics.total_predicted_spp_psi:.0f} psi) near rig equipment ceiling ({self.max_spp:.0f} psi). Backed off pump rate."
            adjusted = True
            constraints["spp_limit_active"] = True

        # 2. Vibration & Stick-Slip Dysfunction Mitigation
        elif telemetry.surface_torque_ft_lbf > 1000.0 and (torque_std_dev / telemetry.surface_torque_ft_lbf) > 0.32:
            rec_rpm = min(curr_rpm + 20.0, self.max_rpm)
            rec_wob = max(curr_wob - 3.0, self.min_wob)
            strategy = "MITIGATE_STICK_SLIP"
            rationale = (
                f"Stick-slip torsional vibration detected (Torque std dev {torque_std_dev:.0f} ft-lbf). "
                f"Increased rotary speed to {rec_rpm:.0f} RPM and trimmed WOB to {rec_wob:.1f} klbf to smooth cutting dynamics."
            )
            adjusted = True
            constraints["stick_slip_active"] = True

        # 3. Bit Balling Mitigation
        elif curr_wob > 25.0 and rate_of_penetration_ft_hr < 15.0 and (mse_current / self.rock_ccs) > 4.5:
            rec_flow = min(curr_flow + 30.0, 600.0)
            rec_wob = max(curr_wob - 5.0, self.min_wob)
            rec_rpm = min(curr_rpm + 15.0, self.max_rpm)
            strategy = "PREVENT_BIT_BALLING"
            rationale = "High MSE with low penetration indicates cutter balling. Increased flow and RPM to flush nozzle jets."
            adjusted = True
            constraints["bit_balling_active"] = True

        # 4. ROP Maximization (Sweet Spot Search)
        elif mse_current < (self.rock_ccs * 2.2) and physics.dynamic_ecd_ppg < (fracture_pressure_ppg - 0.8):
            # Safe margin available: step up WOB and RPM for maximum penetration
            rec_wob = min(curr_wob + 2.0, self.max_wob)
            rec_rpm = min(curr_rpm + 5.0, self.max_rpm)
            strategy = "MAX_ROP"
            rationale = "Wellbore stable with low MSE efficiency ratio. Stepping up WOB and RPM to maximize penetration rate."
            adjusted = True

        # Estimate expected ROP and MSE with new setpoints
        wob_ratio = rec_wob / max(curr_wob, 1.0)
        rpm_ratio = rec_rpm / max(curr_rpm, 1.0)
        expected_rop = rate_of_penetration_ft_hr * (wob_ratio ** 1.1) * (rpm_ratio ** 0.6)
        expected_mse = (rec_wob * 1000.0 / bit_area) + (120.0 * math.pi * rec_rpm * max(telemetry.surface_torque_ft_lbf, 1000.0)) / (bit_area * max(expected_rop, 1.0))

        return AutoDrillerSetpointRecommendation(
            recommended_wob_klbf=round(rec_wob, 1),
            recommended_rpm=round(rec_rpm, 1),
            recommended_flow_rate_gpm=round(rec_flow, 1),
            expected_rop_ft_hr=round(expected_rop, 1),
            expected_mse_psi=round(expected_mse, 1),
            optimization_strategy=strategy,
            is_setpoint_adjusted=adjusted,
            diagnostic_rationale=rationale,
            constraints_active=constraints,
        )
