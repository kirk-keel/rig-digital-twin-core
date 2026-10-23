"""Automated What-If Operational Simulation Sandbox.

Allows rig superintendents and drilling engineers to evaluate hypothetical
operational parameter adjustments (flow rates, mud weight, trip speeds, deepening)
before executing them physically downhole.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from rig_twin.core.models import (
    FluidProperties,
    PhysicsBaseline,
    TelemetryRecord,
    WellGeometry,
)
from rig_twin.physics.engine import RigPhysicsEngine
from rig_twin.physics.torque_drag import TorqueDragEngine


class WhatIfScenarioResult(BaseModel):
    """Predictive outcome of a hypothetical drilling parameter adjustment."""
    scenario_type: str
    parameter_tested: str
    baseline_value: float
    hypothetical_value: float
    predicted_spp_psi: float
    predicted_ecd_ppg: float
    is_safe: bool
    risk_factors: List[str] = Field(default_factory=list)
    engineering_insights: str
    detailed_metrics: Dict[str, Any] = Field(default_factory=dict)


class WhatIfSandbox:
    """Predictive sandbox simulating forward-looking hydraulics and geomechanical scenarios."""

    def __init__(
        self,
        geometry: WellGeometry,
        fluid: FluidProperties,
        current_telemetry: TelemetryRecord,
        pore_pressure_ppg: float = 10.6,
        fracture_pressure_ppg: float = 14.5,
        max_rig_spp_psi: float = 4800.0,
    ):
        self.geometry = geometry
        self.fluid = fluid
        self.telemetry = current_telemetry
        self.pore_ppg = pore_pressure_ppg
        self.frac_ppg = fracture_pressure_ppg
        self.max_spp = max_rig_spp_psi

    def simulate_flow_rate_step(self, target_flow_gpm: float) -> WhatIfScenarioResult:
        """Evaluate pumping rate adjustment: checks SPP limits, jet hydraulics, and ECD margin."""
        mock_tel = copy.deepcopy(self.telemetry)
        mock_tel.flow_rate_in_gpm = target_flow_gpm
        mock_tel.flow_rate_out_gpm = target_flow_gpm

        engine = RigPhysicsEngine(self.geometry, self.fluid)
        baseline = engine.evaluate(mock_tel)

        risks = []
        if baseline.total_predicted_spp_psi > self.max_spp:
            risks.append(f"Standpipe pressure ({baseline.total_predicted_spp_psi:.0f} psi) exceeds rig pump rating ({self.max_spp:.0f} psi)")
        if baseline.dynamic_ecd_ppg > (self.frac_ppg - 0.20):
            risks.append(f"Dynamic ECD ({baseline.dynamic_ecd_ppg:.2f} ppg) breaches fracture margin ({self.frac_ppg:.2f} ppg)")

        is_safe = len(risks) == 0
        insights = (
            f"Stepping flow rate from {self.telemetry.flow_rate_in_gpm:.0f} to {target_flow_gpm:.0f} gpm results in "
            f"SPP = {baseline.total_predicted_spp_psi:.0f} psi and ECD = {baseline.dynamic_ecd_ppg:.2f} ppg. "
            f"Bit HHP: {baseline.bit_hydraulic_horsepower_hhp:.1f} hp."
        )

        return WhatIfScenarioResult(
            scenario_type="FLOW_RATE_STEP_TEST",
            parameter_tested="flow_rate_in_gpm",
            baseline_value=self.telemetry.flow_rate_in_gpm,
            hypothetical_value=target_flow_gpm,
            predicted_spp_psi=baseline.total_predicted_spp_psi,
            predicted_ecd_ppg=baseline.dynamic_ecd_ppg,
            is_safe=is_safe,
            risk_factors=risks,
            engineering_insights=insights,
            detailed_metrics={
                "bit_jet_velocity_fps": baseline.bit_pressure_loss_psi,
                "annular_pressure_loss_psi": baseline.annular_pressure_loss_psi,
                "bit_hhp": baseline.bit_hydraulic_horsepower_hhp,
            },
        )

    def simulate_mud_weight_change(self, target_mud_weight_ppg: float) -> WhatIfScenarioResult:
        """Evaluate mud density adjustment: checks swab/surge bounds and geopressure window."""
        mock_fluid = copy.deepcopy(self.fluid)
        mock_fluid.density_ppg = target_mud_weight_ppg
        mock_tel = copy.deepcopy(self.telemetry)
        mock_tel.mud_weight_in_ppg = target_mud_weight_ppg

        engine = RigPhysicsEngine(self.geometry, mock_fluid)
        baseline = engine.evaluate(mock_tel)

        risks = []
        if baseline.static_ecd_ppg < self.pore_ppg:
            risks.append(f"Static mud weight ({target_mud_weight_ppg:.2f} ppg) is underbalanced relative to pore pressure ({self.pore_ppg:.2f} ppg)")
        if baseline.dynamic_ecd_ppg > (self.frac_ppg - 0.20):
            risks.append(f"Dynamic ECD ({baseline.dynamic_ecd_ppg:.2f} ppg) exceeds fracture gradient ({self.frac_ppg:.2f} ppg)")

        is_safe = len(risks) == 0
        insights = (
            f"Weighting mud from {self.fluid.density_ppg:.2f} to {target_mud_weight_ppg:.2f} ppg shifts "
            f"hydrostatic bottomhole pressure to {baseline.hydrostatic_pressure_psi:.0f} psi. "
            f"Operating ECD: {baseline.dynamic_ecd_ppg:.2f} ppg."
        )

        return WhatIfScenarioResult(
            scenario_type="MUD_WEIGHT_DENSITY_CHANGE",
            parameter_tested="density_ppg",
            baseline_value=self.fluid.density_ppg,
            hypothetical_value=target_mud_weight_ppg,
            predicted_spp_psi=baseline.total_predicted_spp_psi,
            predicted_ecd_ppg=baseline.dynamic_ecd_ppg,
            is_safe=is_safe,
            risk_factors=risks,
            engineering_insights=insights,
            detailed_metrics={
                "hydrostatic_pressure_psi": baseline.hydrostatic_pressure_psi,
                "static_trip_margin_ppg": round(target_mud_weight_ppg - self.pore_ppg, 2),
            },
        )

    def simulate_tripping_speed(self, target_velocity_ft_min: float) -> WhatIfScenarioResult:
        """Evaluate proposed tripping pulling (negative) or running (positive) speed."""
        mock_tel = copy.deepcopy(self.telemetry)
        mock_tel.string_velocity_ft_min = target_velocity_ft_min
        mock_tel.flow_rate_in_gpm = 0.0
        mock_tel.flow_rate_out_gpm = 0.0

        engine = RigPhysicsEngine(self.geometry, self.fluid)
        baseline = engine.evaluate(mock_tel)

        risks = []
        if target_velocity_ft_min < 0:
            # Tripping out -> Swab underbalance check
            if baseline.effective_ecd_swab_ppg < self.pore_ppg:
                risks.append(
                    f"Swab pressure loss ({baseline.swab_pressure_loss_psi:.1f} psi) drops effective ECD "
                    f"({baseline.effective_ecd_swab_ppg:.2f} ppg) below pore pressure ({self.pore_ppg:.2f} ppg)"
                )
            test_ecd = baseline.effective_ecd_swab_ppg
        else:
            # Tripping in -> Surge fracture check
            if baseline.effective_ecd_surge_ppg > (self.frac_ppg - 0.20):
                risks.append(
                    f"Surge pressure excess ({baseline.surge_pressure_loss_psi:.1f} psi) pushes effective ECD "
                    f"({baseline.effective_ecd_surge_ppg:.2f} ppg) above fracture limit ({self.frac_ppg:.2f} ppg)"
                )
            test_ecd = baseline.effective_ecd_surge_ppg

        is_safe = len(risks) == 0
        action = "POOH (Pulling Out)" if target_velocity_ft_min < 0 else "RIH (Running In)"
        insights = (
            f"{action} at {abs(target_velocity_ft_min):.0f} ft/min generates dynamic bottomhole "
            f"pressure delta of {max(baseline.surge_pressure_loss_psi, baseline.swab_pressure_loss_psi):.1f} psi "
            f"(Effective ECD: {test_ecd:.2f} ppg)."
        )

        return WhatIfScenarioResult(
            scenario_type="TRIPPING_SPEED_ADJUSTMENT",
            parameter_tested="string_velocity_ft_min",
            baseline_value=self.telemetry.string_velocity_ft_min,
            hypothetical_value=target_velocity_ft_min,
            predicted_spp_psi=0.0,
            predicted_ecd_ppg=test_ecd,
            is_safe=is_safe,
            risk_factors=risks,
            engineering_insights=insights,
            detailed_metrics={
                "surge_pressure_psi": baseline.surge_pressure_loss_psi,
                "swab_pressure_loss_psi": baseline.swab_pressure_loss_psi,
            },
        )
