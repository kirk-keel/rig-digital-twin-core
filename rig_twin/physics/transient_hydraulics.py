"""Hydraulic Transient Waterhammer & MPD Choke Surge Pressure Simulator.

Computes acoustic wave propagation speeds in drilling mud columns,
Joukowsky waterhammer pressure surges, and round-trip acoustic reflections during rapid choke/pump actions.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel

from rig_twin.core.models import FluidProperties


class TransientSurgeResult(BaseModel):
    """Calculated hydraulic waterhammer transient parameters and wave reflections."""
    mud_acoustic_speed_fps: float
    round_trip_acoustic_time_sec: float
    steady_state_velocity_fps: float
    closure_time_sec: float
    is_rapid_closure: bool  # True if closure_time <= round_trip_time (full Joukowsky surge)
    joukowsky_peak_surge_psi: float
    effective_surge_pressure_psi: float
    total_transient_peak_pressure_psi: float
    casing_burst_rating_psi: float
    casing_burst_safety_factor: float
    is_burst_limit_threatened: bool
    wave_pressure_profile: List[Dict[str, float]]


class TransientHydraulicsEngine:
    """Models 1D acoustic waterhammer waves and dynamic surge pressures in the mud column."""

    def __init__(
        self,
        fluid: FluidProperties,
        pipe_inner_diameter_in: float = 4.276,
        pipe_wall_thickness_in: float = 0.362,
        well_depth_ft: float = 11450.0,
        bulk_modulus_psi: float = 380000.0,
        steel_modulus_psi: float = 30e6,
        casing_burst_rating_psi: float = 8500.0,
    ):
        self.fluid = fluid
        self.pipe_id = pipe_inner_diameter_in
        self.wall_t = pipe_wall_thickness_in
        self.depth_ft = well_depth_ft
        self.bulk_modulus = bulk_modulus_psi
        self.steel_modulus = steel_modulus_psi
        self.casing_burst_rating = casing_burst_rating_psi

    def acoustic_wave_speed_fps(self) -> float:
        """Calculate fluid acoustic wave speed in elastic steel pipe:
        
        c = sqrt( (B_m / rho_m) / (1 + (B_m / E) * (D / t)) )
        """
        rho_mud_lb_cu_ft = self.fluid.density_ppg * 7.48052
        rho_mud_slugs = rho_mud_lb_cu_ft / 32.174

        bm_psf = self.bulk_modulus * 144.0
        elastic_term = 1.0 + (self.bulk_modulus / self.steel_modulus) * (self.pipe_id / max(self.wall_t, 0.05))

        c_fps = math.sqrt((bm_psf / max(rho_mud_slugs, 0.1)) / max(elastic_term, 1.0))
        return min(max(c_fps, 2800.0), 4500.0)

    def simulate_valve_closure_surge(
        self,
        flow_rate_gpm: float,
        valve_closure_time_sec: float = 0.5,
        steady_state_pressure_psi: float = 4085.0,
    ) -> TransientSurgeResult:
        """Compute transient Joukowsky waterhammer pressure surge and reflections."""
        c_fps = self.acoustic_wave_speed_fps()
        # Round trip acoustic travel time: t_rt = 2 * L / c
        t_rt = (2.0 * self.depth_ft) / c_fps

        # Velocity in pipe bore: v = Q / (2.448 * ID^2) [ft/s]
        id_sq = self.pipe_id ** 2
        v_fps = flow_rate_gpm / (2.448 * id_sq) if id_sq > 0 else 0.0

        # Joukowsky maximum pressure surge: dP_max = (rho[ppg] * c[fps] * delta_v[fps]) / 619.34
        dp_joukowsky = (self.fluid.density_ppg * c_fps * v_fps) / 619.34

        # Closure regime: rapid (closure <= t_rt) vs gradual (closure > t_rt)
        is_rapid = valve_closure_time_sec <= t_rt
        if is_rapid:
            effective_surge = dp_joukowsky
        else:
            # Gradual closure damping
            effective_surge = dp_joukowsky * (t_rt / max(valve_closure_time_sec, 0.05))

        total_peak = steady_state_pressure_psi + effective_surge
        safety_factor = self.casing_burst_rating / max(total_peak, 1.0)
        is_threatened = total_peak > (self.casing_burst_rating * 0.90)

        # Generate 1D wave time-series profile across 4 reflection periods
        wave_profile = []
        n_steps = 30
        dt = (t_rt * 3.0) / n_steps

        for i in range(n_steps + 1):
            t = i * dt
            # Decaying standing wave simulation with viscous damping
            damping = math.exp(-0.8 * (t / t_rt))
            wave_oscillation = math.cos(2.0 * math.pi * (t / t_rt))
            instantaneous_surge = effective_surge * damping * wave_oscillation if t >= valve_closure_time_sec else (effective_surge * (t / max(valve_closure_time_sec, 0.01)))
            p_inst = steady_state_pressure_psi + instantaneous_surge

            wave_profile.append({
                "time_sec": round(t, 3),
                "transient_pressure_psi": round(p_inst, 1),
                "surge_component_psi": round(instantaneous_surge, 1),
            })

        return TransientSurgeResult(
            mud_acoustic_speed_fps=round(c_fps, 1),
            round_trip_acoustic_time_sec=round(t_rt, 3),
            steady_state_velocity_fps=round(v_fps, 2),
            closure_time_sec=round(valve_closure_time_sec, 3),
            is_rapid_closure=is_rapid,
            joukowsky_peak_surge_psi=round(dp_joukowsky, 1),
            effective_surge_pressure_psi=round(effective_surge, 1),
            total_transient_peak_pressure_psi=round(total_peak, 1),
            casing_burst_rating_psi=round(self.casing_burst_rating, 1),
            casing_burst_safety_factor=round(safety_factor, 2),
            is_burst_limit_threatened=is_threatened,
            wave_pressure_profile=wave_profile,
        )
