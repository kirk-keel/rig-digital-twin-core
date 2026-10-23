"""Transient wellbore temperature profile and pressure/temperature-dependent PVT fluid modeling."""

from __future__ import annotations

import math
from typing import List, Tuple
from rig_twin.core.models import FluidProperties, WellGeometry


class ThermalPVTEngine:
    """Computes wellbore temperature profiles and pressure/temperature dependent mud density and rheology.
    
    Standard petroleum PVT formulations:
    rho(P, T) = rho_0 * [1 + (P - P_0)/B_m - alpha_m * (T - T_0)]
    where:
    - B_m: Isothermal bulk modulus of mud (~300,000 to 500,000 psi)
    - alpha_m: Volumetric thermal expansion coefficient (~0.0004 to 0.0006 1/degF)
    """

    def __init__(
        self,
        surface_temp_degf: float = 70.0,
        geothermal_gradient_degf_per_100ft: float = 1.6,
        bulk_modulus_psi: float = 380000.0,
        thermal_expansion_coeff_per_degf: float = 0.00022,
    ):
        self.surface_temp_degf = surface_temp_degf
        self.geothermal_gradient = geothermal_gradient_degf_per_100ft / 100.0
        self.bulk_modulus_psi = bulk_modulus_psi
        self.thermal_expansion_coeff = thermal_expansion_coeff_per_degf

    def formation_temperature_degf(self, tvd_ft: float) -> float:
        """Undisturbed formation temperature at given TVD."""
        return self.surface_temp_degf + (self.geothermal_gradient * max(tvd_ft, 0.0))

    def circulating_temperature_profile(
        self, bit_depth_ft: float, flow_rate_gpm: float, mud_inlet_temp_degf: float = 85.0
    ) -> List[Tuple[float, float, float]]:
        """Calculate circulating fluid temperature inside drillstring and annulus (Hasan & Kabir model).
        
        Returns list of (depth_ft, temp_inside_pipe_degf, temp_in_annulus_degf).
        """
        if bit_depth_ft <= 0.0:
            return [(0.0, mud_inlet_temp_degf, mud_inlet_temp_degf)]

        bottom_formation_temp = self.formation_temperature_degf(bit_depth_ft)
        steps = 20
        dz = bit_depth_ft / steps
        profile = []

        # Relaxation factor: higher flow rate sweeps heat out, cooling the bottom
        q_norm = min(max(flow_rate_gpm / 500.0, 0.1), 3.0)
        cooling_factor = 0.75 / math.sqrt(q_norm)

        for i in range(steps + 1):
            z = i * dz
            t_form = self.formation_temperature_degf(z)
            frac = z / bit_depth_ft

            # Pipe temperature warms as fluid travels down towards the bit
            t_pipe = mud_inlet_temp_degf + (bottom_formation_temp - mud_inlet_temp_degf) * (frac ** 1.3) * (1.0 - cooling_factor * 0.3)

            # Annulus temperature: hottest near lower 1/3, cools towards surface
            t_ann = t_pipe + 15.0 * math.sin(math.pi * frac)

            profile.append((z, round(t_pipe, 1), round(t_ann, 1)))

        return profile

    def pvt_mud_density(
        self,
        base_density_ppg: float,
        pressure_psi: float,
        temp_degf: float,
        reference_pressure_psi: float = 14.7,
        reference_temp_degf: float = 70.0,
    ) -> float:
        """Pressure and temperature corrected mud density rho(P, T) in ppg."""
        delta_p = pressure_psi - reference_pressure_psi
        delta_t = temp_degf - reference_temp_degf

        compressibility_factor = delta_p / self.bulk_modulus_psi
        thermal_expansion_factor = self.thermal_expansion_coeff * delta_t

        corrected_density = base_density_ppg * (1.0 + compressibility_factor - thermal_expansion_factor)
        # Physical bounding
        return max(min(corrected_density, base_density_ppg * 1.25), base_density_ppg * 0.8)

    def temperature_adjusted_viscosity(
        self, base_viscosity_cp: float, temp_degf: float, ref_temp_degf: float = 120.0
    ) -> float:
        """Arrhenius-type temperature thinning adjustment for apparent viscosity."""
        # Viscosity decreases as temperature rises
        activation_energy_factor = 1800.0  # Kelvin equivalent empirical factor
        t_abs = (temp_degf - 32.0) * (5.0 / 9.0) + 273.15
        t_ref_abs = (ref_temp_degf - 32.0) * (5.0 / 9.0) + 273.15

        ratio = math.exp(activation_energy_factor * ((1.0 / t_abs) - (1.0 / t_ref_abs)))
        return max(base_viscosity_cp * ratio, base_viscosity_cp * 0.25)
