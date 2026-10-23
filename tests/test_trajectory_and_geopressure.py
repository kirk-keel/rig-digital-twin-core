"""Unit tests for 3D trajectory (Minimum Curvature) and geopressure Eaton prediction."""

import math
import pytest
from rig_twin.physics.trajectory import (
    DirectionalTrajectoryEngine,
    SurveyStation,
    TrajectoryPoint,
)
from rig_twin.physics.geopressure import GeopressureEngine


def test_minimum_curvature_step():
    s1 = SurveyStation(measured_depth_ft=0.0, inclination_deg=0.0, azimuth_deg=0.0)
    s2 = SurveyStation(measured_depth_ft=100.0, inclination_deg=10.0, azimuth_deg=90.0)

    delta_tvd, delta_north, delta_east, dls = DirectionalTrajectoryEngine.minimum_curvature_step(s1, s2)
    assert 95.0 < delta_tvd < 100.0
    assert delta_east > 0.0
    assert math.isclose(dls, 10.0, rel_tol=1e-5)  # 10 deg over 100 ft


def test_trajectory_computation_and_interpolation():
    engine = DirectionalTrajectoryEngine(vertical_section_azimuth_deg=45.0)
    stations = [
        SurveyStation(measured_depth_ft=0.0, inclination_deg=0.0, azimuth_deg=45.0),
        SurveyStation(measured_depth_ft=1000.0, inclination_deg=0.0, azimuth_deg=45.0),
        SurveyStation(measured_depth_ft=2000.0, inclination_deg=20.0, azimuth_deg=45.0),
        SurveyStation(measured_depth_ft=4000.0, inclination_deg=20.0, azimuth_deg=45.0),
    ]
    points = engine.compute_trajectory(stations)
    assert len(points) == 4
    assert points[-1].true_vertical_depth_ft < 4000.0
    assert points[-1].northing_ft > 0.0
    assert points[-1].easting_ft > 0.0

    # Interpolate at MD = 1500 ft (halfway into build section)
    interp = engine.interpolate_position(points, target_md_ft=1500.0)
    assert 1000.0 < interp.measured_depth_ft < 2000.0
    assert 0.0 < interp.inclination_deg < 20.0


def test_geopressure_eaton_prediction():
    engine = GeopressureEngine(nctl_surface_d_exp=1.0, nctl_slope_per_1000ft=0.04)
    # At shallow depth (3000 ft) with normal drilling (d_xc tracks NCTL)
    shallow = engine.predict_pressures(
        tvd_ft=3000.0,
        rop_ft_hr=60.0,
        rpm=120.0,
        wob_klbf=22.0,
        bit_diameter_in=8.5,
        current_mud_weight_ppg=9.5,
    )
    assert shallow.pore_pressure_ppg >= engine.normal_pp_ppg
    assert shallow.fracture_gradient_ppg > shallow.pore_pressure_ppg

    # In overpressured zone (11500 ft): fast ROP / low WOB in undercompacted shale causes d_xc to drop well below NCTL
    deep = engine.predict_pressures(
        tvd_ft=11500.0,
        rop_ft_hr=160.0,
        rpm=90.0,
        wob_klbf=10.0,
        bit_diameter_in=8.5,
        current_mud_weight_ppg=11.2,
    )
    assert deep.pore_pressure_psi > 5000.0
    assert deep.fracture_gradient_psi > deep.pore_pressure_psi
    assert deep.is_overpressured
