"""Integrated Rig Physics Engine combining hydraulics, rheology, and tripping dynamics."""

from __future__ import annotations

from typing import Optional
from rig_twin.core.models import (
    FluidProperties,
    PhysicsBaseline,
    TelemetryRecord,
    WellGeometry,
)
from rig_twin.physics.hydraulics import HydraulicsEngine
from rig_twin.physics.rheology import RheologyEngine
from rig_twin.physics.surge_swab import SurgeSwabEngine


class RigPhysicsEngine:
    """Core deterministic physics simulator for drilling and tripping operations."""

    def __init__(self, geometry: WellGeometry, fluid: FluidProperties):
        self.geometry = geometry
        self.fluid = fluid
        self.rheology_engine = RheologyEngine(fluid)
        self.hydraulics_engine = HydraulicsEngine(geometry, fluid)
        self.surge_swab_engine = SurgeSwabEngine(geometry, fluid)

    def update_fluid(self, fluid: FluidProperties) -> None:
        """Update active fluid properties (e.g. mud weight changes or rheology tests)."""
        self.fluid = fluid
        self.rheology_engine = RheologyEngine(fluid)
        self.hydraulics_engine = HydraulicsEngine(self.geometry, fluid)
        self.surge_swab_engine = SurgeSwabEngine(self.geometry, fluid)

    def evaluate(self, telemetry: TelemetryRecord) -> PhysicsBaseline:
        """Calculate complete deterministic physics baseline corresponding to a telemetry record."""
        # Use dynamic mud weight if telemetry reports mud weight in
        if telemetry.mud_weight_in_ppg > 0 and abs(telemetry.mud_weight_in_ppg - self.fluid.density_ppg) > 0.05:
            self.fluid.density_ppg = telemetry.mud_weight_in_ppg

        tvd = max(telemetry.true_vertical_depth_ft, 1.0)
        bit_d = max(telemetry.bit_depth_ft, 1.0)
        q_gpm = max(telemetry.flow_rate_in_gpm, 0.0)

        # 1. Static Hydrostatic Pressure
        p_hydro = self.hydraulics_engine.hydrostatic_pressure_psi(tvd)
        static_ecd = self.fluid.density_ppg

        # 2. Frictional losses
        p_surf = self.hydraulics_engine.surface_equipment_loss_psi(q_gpm)
        p_pipe, pipe_segments = self.hydraulics_engine.pipe_internal_losses_psi(q_gpm, bit_d)
        p_bit, v_jet, hhp, f_imp = self.hydraulics_engine.bit_pressure_loss_psi(
            q_gpm, self.geometry.bit
        )
        apl, ann_segments, ann_regime = self.hydraulics_engine.annular_pressure_loss_psi(
            q_gpm, bit_d
        )

        total_predicted_spp = p_surf + p_pipe + p_bit + apl
        dynamic_ecd = self.hydraulics_engine.equivalent_circulating_density_ppg(apl, tvd)

        # Pipe regime estimation
        pipe_regime = "LAMINAR"
        if pipe_segments:
            pipe_regime = pipe_segments[0].get("regime", "LAMINAR")

        # 3. Dynamic Tripping Pressure (Surge / Swab)
        surge_psi, swab_psi = self.surge_swab_engine.calculate_surge_swab_psi(
            string_velocity_ft_min=telemetry.string_velocity_ft_min,
            bit_depth_ft=bit_d,
            is_float_closed=True,
        )

        effective_ecd_surge = dynamic_ecd + (surge_psi / (0.052 * tvd))
        effective_ecd_swab = max(
            dynamic_ecd - (swab_psi / (0.052 * tvd)),
            self.fluid.density_ppg - (swab_psi / (0.052 * tvd)),
            0.0,
        )

        return PhysicsBaseline(
            timestamp=telemetry.timestamp,
            well_id=telemetry.well_id,
            measured_depth_ft=telemetry.measured_depth_ft,
            hydrostatic_pressure_psi=round(p_hydro, 2),
            annular_pressure_loss_psi=round(apl, 2),
            pipe_internal_pressure_loss_psi=round(p_pipe, 2),
            bit_pressure_loss_psi=round(p_bit, 2),
            total_predicted_spp_psi=round(total_predicted_spp, 2),
            static_ecd_ppg=round(static_ecd, 3),
            dynamic_ecd_ppg=round(dynamic_ecd, 3),
            surge_pressure_loss_psi=round(surge_psi, 2),
            swab_pressure_loss_psi=round(swab_psi, 2),
            effective_ecd_surge_ppg=round(effective_ecd_surge, 3),
            effective_ecd_swab_ppg=round(effective_ecd_swab, 3),
            annulus_flow_regime=ann_regime,
            pipe_flow_regime=pipe_regime,
            bit_jet_impact_force_lbf=round(f_imp, 2),
            bit_hydraulic_horsepower_hhp=round(hhp, 2),
        )
