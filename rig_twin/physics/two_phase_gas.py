"""Two-Phase gas-liquid drift-flux model and gas influx migration simulator."""

from __future__ import annotations

import math
from typing import Dict, List, Optional
from rig_twin.core.models import FluidProperties


class TwoPhaseGasEngine:
    """Drift-flux two-phase model simulating gas bubble migration, slip, and Boyle expansion."""

    def __init__(
        self,
        fluid: FluidProperties,
        distribution_coeff_c0: float = 1.20,
        drift_velocity_fps: float = 1.10,
    ):
        self.fluid = fluid
        self.c0 = distribution_coeff_c0
        self.vd = drift_velocity_fps

    def gas_migration_velocity_fps(self, mixture_velocity_fps: float) -> float:
        """Zuber-Findlay drift-flux gas velocity: vg = C0 * vm + vd."""
        return (self.c0 * abs(mixture_velocity_fps)) + self.vd

    def gas_z_factor(self, pressure_psi: float, temp_degf: float) -> float:
        """Hall-Yarborough / Papay pseudo-reduced compressibility z-factor approximation."""
        # For typical methane gas (Tc ≈ 343 R, Pc ≈ 667 psia)
        t_rankine = temp_degf + 459.67
        pr = pressure_psi / 667.0
        tr = t_rankine / 343.0
        # Papay empirical correlation
        z = 1.0 - (3.52 * pr / (10 ** (0.9813 * tr))) + (0.274 * (pr ** 2) / (10 ** (0.8157 * tr)))
        return min(max(z, 0.65), 1.35)

    def simulate_kick_migration(
        self,
        initial_depth_ft: float,
        initial_pit_gain_bbl: float,
        mixture_flow_gpm: float,
        hole_diameter_in: float,
        pipe_od_in: float,
        time_elapsed_min: float,
        choke_pressure_psi: float = 0.0,
    ) -> Dict[str, float]:
        """Simulate the position, volume expansion, and surface arrival time of a gas influx.
        
        Args:
            initial_depth_ft: Depth where influx entered the well.
            initial_pit_gain_bbl: Volume of influx at downhole condition.
            mixture_flow_gpm: Circulating flow rate (0 if shut-in).
            hole_diameter_in: Hole diameter.
            pipe_od_in: Drillpipe OD.
            time_elapsed_min: Time since influx entered.
            choke_pressure_psi: Surface backpressure applied.
        """
        annulus_cap_bbl_ft = (hole_diameter_in ** 2 - pipe_od_in ** 2) / 1029.4
        annulus_area_sq_in = (hole_diameter_in ** 2 - pipe_od_in ** 2) * 2.448

        vm_fps = (mixture_flow_gpm / annulus_area_sq_in) if annulus_area_sq_in > 0 else 0.0
        vg_fps = self.gas_migration_velocity_fps(vm_fps)

        # Distance migrated
        distance_migrated_ft = vg_fps * (time_elapsed_min * 60.0)
        current_depth_ft = max(initial_depth_ft - distance_migrated_ft, 0.0)

        # In-situ pressures
        p_init = (0.052 * self.fluid.density_ppg * initial_depth_ft) + choke_pressure_psi
        p_curr = (0.052 * self.fluid.density_ppg * current_depth_ft) + choke_pressure_psi
        p_curr = max(p_curr, 14.7 + choke_pressure_psi)

        # Real gas expansion: V2 = V1 * (P1 / P2) * (T2 / T1) * (Z2 / Z1)
        # Geothermal temperature calculation (70 degF surface + 1.6 degF/100ft)
        t1_degf = 70.0 + (0.016 * initial_depth_ft)
        t2_degf = 70.0 + (0.016 * current_depth_ft)
        t1_r = t1_degf + 459.67
        t2_r = t2_degf + 459.67

        z1 = self.gas_z_factor(p_init, t1_degf)
        z2 = self.gas_z_factor(p_curr, t2_degf)

        expansion_ratio = (p_init / p_curr) * (z2 / z1) * (t2_r / t1_r)
        current_volume_bbl = initial_pit_gain_bbl * min(max(expansion_ratio, 1.0), 25.0)

        # Time remaining until gas reaches surface/BOP
        if current_depth_ft > 0.0:
            time_to_surface_min = current_depth_ft / (vg_fps * 60.0)
        else:
            time_to_surface_min = 0.0

        return {
            "current_gas_depth_ft": round(current_depth_ft, 1),
            "gas_velocity_fps": round(vg_fps, 2),
            "expanded_gas_volume_bbl": round(current_volume_bbl, 2),
            "expansion_ratio": round(expansion_ratio, 2),
            "time_to_surface_min": round(time_to_surface_min, 1),
            "has_reached_surface": current_depth_ft <= 0.0,
        }
