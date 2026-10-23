"""BHA Dynamics & 3-Axis Drillstring Vibration Modal Engine.

Calculates natural acoustic resonance frequencies, stick-slip phase trajectories,
BHA lateral whirl critical speeds (Campbell diagram), and safe operating RPM bands.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class VibrationResonanceBand(BaseModel):
    """Identified critical rotary speed band prone to severe resonance."""
    mode: str  # "AXIAL", "TORSIONAL", "FORWARD_WHIRL", "BACKWARD_WHIRL"
    center_rpm: float
    min_rpm: float
    max_rpm: float
    severity: str  # "CRITICAL", "MODERATE", "LOW"
    harmonics: int


class BHAWhirlEvaluation(BaseModel):
    """BHA lateral and backward whirl analysis results."""
    forward_whirl_critical_rpm: float
    backward_whirl_critical_rpm: float
    axial_bit_bounce_natural_freq_hz: float
    axial_critical_rpm: float
    torsional_stick_slip_natural_freq_hz: float
    torsional_critical_rpm: float
    safe_rpm_windows: List[Tuple[float, float]]
    resonance_bands: List[VibrationResonanceBand]


class DrillstringDynamicsEngine:
    """Models 3-axis vibration modes: Axial (bit bounce), Torsional (stick-slip), and Lateral (whirl)."""

    def __init__(
        self,
        drillstring_length_ft: float = 11450.0,
        bha_length_ft: float = 600.0,
        collar_od_in: float = 6.5,
        collar_id_in: float = 2.813,
        stabilizer_spacing_ft: float = 60.0,
        hole_diameter_in: float = 8.5,
        bit_roller_cones_count: int = 3,  # 3-cone or PDC blade cutter count
    ):
        self.length_ft = drillstring_length_ft
        self.bha_len_ft = bha_length_ft
        self.collar_od_in = collar_od_in
        self.collar_id_in = collar_id_in
        self.span_ft = stabilizer_spacing_ft
        self.hole_diam_in = hole_diameter_in
        self.cutters_count = bit_roller_cones_count

        # Steel acoustic properties
        self.youngs_modulus_psi = 30e6
        self.shear_modulus_psi = 11.5e6
        self.steel_density_lb_cu_ft = 489.5
        # Acoustic propagation speeds in steel
        self.c_axial_fps = 16800.0   # ~5120 m/s
        self.c_torsional_fps = 10400.0 # ~3170 m/s

    def axial_bit_bounce_frequencies(self) -> Tuple[float, float]:
        """Acoustic fundamental axial frequency and corresponding critical surface RPM.
        
        f_axial = c_axial / (4 * L) (fixed-free or fixed-spring)
        RPM_crit = (f_axial * 60) / cutter_count
        """
        f_axial = self.c_axial_fps / (4.0 * max(self.length_ft, 100.0))
        # Excitation occurs when bit cutters/cones strike formation: excitation frequency = RPM * count / 60
        rpm_axial = (f_axial * 60.0) / max(self.cutters_count, 1)
        return round(f_axial, 3), round(rpm_axial, 1)

    def torsional_resonance_frequencies(self) -> Tuple[float, float]:
        """Fundamental torsional frequency (quarter-wave resonance) and critical stick-slip RPM.
        
        f_torsional = c_torsional / (4 * L)
        """
        f_torsional = self.c_torsional_fps / (4.0 * max(self.length_ft, 100.0))
        # Torsional 1st harmonic critical RPM
        rpm_torsional = f_torsional * 60.0
        return round(f_torsional, 3), round(rpm_torsional, 1)

    def lateral_bha_whirl_speeds(self) -> Tuple[float, float]:
        """Forward and backward lateral BHA whirl critical speeds using Euler-Bernoulli beam theory.
        
        omega_n = (pi / L_span)^2 * sqrt(E * I / (rho * A))
        """
        od_ft = self.collar_od_in / 12.0
        id_ft = self.collar_id_in / 12.0
        span_ft = max(self.span_ft, 10.0)

        # Moment of Inertia: I = pi/64 * (OD^4 - ID^4)
        inertia_ft4 = (math.pi / 64.0) * (od_ft ** 4 - id_ft ** 4)
        area_sq_ft = (math.pi / 4.0) * (od_ft ** 2 - id_ft ** 2)
        mass_per_ft = area_sq_ft * (self.steel_density_lb_cu_ft / 32.174)  # slugs/ft

        e_psf = self.youngs_modulus_psi * 144.0  # lbf/sq ft
        omega_natural_rad_s = ((math.pi / span_ft) ** 2) * math.sqrt((e_psf * inertia_ft4) / max(mass_per_ft, 0.1))

        # Forward synchronous whirl: RPM_fw = omega * 60 / (2 * pi)
        rpm_forward = (omega_natural_rad_s * 60.0) / (2.0 * math.pi)

        # Backward whirl clearance factor: ratio of collar OD to annular radial clearance
        radial_clearance = max(self.hole_diam_in - self.collar_od_in, 0.5)
        kinematic_ratio = (self.collar_od_in / radial_clearance) + 1.0
        rpm_backward = rpm_forward / kinematic_ratio

        return round(rpm_forward, 1), round(rpm_backward, 1)

    def evaluate_safe_operating_rpm_bands(
        self, min_operating_rpm: float = 40.0, max_operating_rpm: float = 200.0
    ) -> BHAWhirlEvaluation:
        """Construct Campbell resonance map and identify safe RPM windows for the driller."""
        f_ax, rpm_ax = self.axial_bit_bounce_frequencies()
        f_tor, rpm_tor = self.torsional_resonance_frequencies()
        rpm_fw, rpm_bw = self.lateral_bha_whirl_speeds()

        bands: List[VibrationResonanceBand] = []

        # Torsional harmonics (1x, 2x, 3x)
        for h in range(1, 4):
            center = rpm_tor * h
            if min_operating_rpm <= center <= max_operating_rpm:
                bands.append(VibrationResonanceBand(
                    mode="TORSIONAL",
                    center_rpm=round(center, 1),
                    min_rpm=round(center - 6.0, 1),
                    max_rpm=round(center + 6.0, 1),
                    severity="CRITICAL" if h == 1 else "MODERATE",
                    harmonics=h,
                ))

        # Axial bit bounce (1x, 2x)
        for h in range(1, 3):
            center = rpm_ax * h
            if min_operating_rpm <= center <= max_operating_rpm:
                bands.append(VibrationResonanceBand(
                    mode="AXIAL",
                    center_rpm=round(center, 1),
                    min_rpm=round(center - 8.0, 1),
                    max_rpm=round(center + 8.0, 1),
                    severity="CRITICAL",
                    harmonics=h,
                ))

        # Lateral BHA Whirl
        if min_operating_rpm <= rpm_fw <= max_operating_rpm:
            bands.append(VibrationResonanceBand(
                mode="FORWARD_WHIRL",
                center_rpm=rpm_fw,
                min_rpm=round(rpm_fw - 10.0, 1),
                max_rpm=round(rpm_fw + 10.0, 1),
                severity="CRITICAL",
                harmonics=1,
            ))

        if min_operating_rpm <= rpm_bw <= max_operating_rpm:
            bands.append(VibrationResonanceBand(
                mode="BACKWARD_WHIRL",
                center_rpm=rpm_bw,
                min_rpm=round(rpm_bw - 8.0, 1),
                max_rpm=round(rpm_bw + 8.0, 1),
                severity="CRITICAL",
                harmonics=1,
            ))

        # Sort bands by center RPM
        bands.sort(key=lambda b: b.center_rpm)

        # Invert to find safe RPM gaps
        safe_windows: List[Tuple[float, float]] = []
        current_rpm = min_operating_rpm

        for b in bands:
            if b.min_rpm > current_rpm + 5.0:
                safe_windows.append((round(current_rpm, 1), round(b.min_rpm, 1)))
            current_rpm = max(current_rpm, b.max_rpm)

        if current_rpm < max_operating_rpm - 5.0:
            safe_windows.append((round(current_rpm, 1), round(max_operating_rpm, 1)))

        return BHAWhirlEvaluation(
            forward_whirl_critical_rpm=rpm_fw,
            backward_whirl_critical_rpm=rpm_bw,
            axial_bit_bounce_natural_freq_hz=f_ax,
            axial_critical_rpm=rpm_ax,
            torsional_stick_slip_natural_freq_hz=f_tor,
            torsional_critical_rpm=rpm_tor,
            safe_rpm_windows=safe_windows,
            resonance_bands=bands,
        )
