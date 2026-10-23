"""Unit tests for advanced petroleum physics: Thermal PVT, Torque & Drag, Cuttings, Gas & Kill Sheet."""

import math
import pytest
from rig_twin.demo import build_sample_well
from rig_twin.physics.thermal_pvt import ThermalPVTEngine
from rig_twin.physics.torque_drag import TorqueDragEngine
from rig_twin.physics.cuttings_transport import CuttingsTransportEngine
from rig_twin.physics.two_phase_gas import TwoPhaseGasEngine
from rig_twin.physics.safe_trip_envelope import SafeTripEnvelopeOptimizer
from rig_twin.physics.well_control_kill_sheet import (
    WellControlEngine,
    WellControlInput,
)
from rig_twin.physics.mse_optimizer import MSEDrillingOptimizer


@pytest.fixture
def well_and_fluid():
    return build_sample_well()


def test_thermal_pvt_density():
    pvt = ThermalPVTEngine()
    # At high pressure downhole (6000 psi) and moderate temp (140 degF), compressibility increases density
    rho_downhole = pvt.pvt_mud_density(base_density_ppg=11.2, pressure_psi=6000.0, temp_degf=140.0)
    assert rho_downhole > 11.2

    # Circulating temperature profile
    profile = pvt.circulating_temperature_profile(bit_depth_ft=10000.0, flow_rate_gpm=500.0)
    assert len(profile) == 21
    assert profile[-1][1] > 100.0  # Pipe bottom temperature


def test_torque_drag_johancsik(well_and_fluid):
    well, fluid = well_and_fluid
    td_engine = TorqueDragEngine(well, fluid)
    
    loads = td_engine.calculate_hookload_and_torque(bit_depth_ft=11400.0, friction_coeff=0.25)
    # Pick-up must be strictly greater than rotating, which must be strictly greater than slack-off
    assert loads["pickup_hookload_klbf"] > loads["rotating_hookload_klbf"]
    assert loads["rotating_hookload_klbf"] > loads["slackoff_hookload_klbf"]
    assert loads["surface_torque_ft_lbf"] > 1000.0
    assert loads["sinusoidal_buckling_limit_klbf"] > 0.0

    # Broomstick curves
    envelope = td_engine.generate_broomstick_envelope(max_depth_ft=5000.0, step_ft=1000.0)
    assert len(envelope) == 5
    assert "pickup_mu_0.25" in envelope[0]


def test_cuttings_transport(well_and_fluid):
    _, fluid = well_and_fluid
    ct = CuttingsTransportEngine(fluid)

    res = ct.evaluate_hole_cleaning(
        annular_velocity_fps=2.8,
        rate_of_penetration_ft_hr=60.0,
        hole_diameter_in=8.5,
        pipe_od_in=5.0,
    )
    assert res["hole_cleaning_index"] > 0.5
    assert res["transport_ratio"] > 0.4
    assert res["annular_friction_multiplier"] >= 1.0


def test_two_phase_gas_migration(well_and_fluid):
    _, fluid = well_and_fluid
    gas_engine = TwoPhaseGasEngine(fluid)

    res = gas_engine.simulate_kick_migration(
        initial_depth_ft=11000.0,
        initial_pit_gain_bbl=15.0,
        mixture_flow_gpm=0.0,  # Shut-in migration
        hole_diameter_in=8.5,
        pipe_od_in=5.0,
        time_elapsed_min=30.0,
    )
    assert res["current_gas_depth_ft"] < 11000.0
    assert res["expanded_gas_volume_bbl"] > 15.0  # Gas expands as it rises
    assert res["time_to_surface_min"] > 0.0


def test_safe_trip_envelope_optimizer(well_and_fluid):
    well, fluid = well_and_fluid
    optimizer = SafeTripEnvelopeOptimizer(well, fluid, pore_pressure_ppg=10.5, fracture_pressure_ppg=14.5)

    pooh_speed = optimizer.calculate_max_safe_pooh_speed_ft_min(bit_depth_ft=11000.0)
    rih_speed = optimizer.calculate_max_safe_rih_speed_ft_min(bit_depth_ft=11000.0)

    assert 10.0 <= pooh_speed <= 300.0
    assert 10.0 <= rih_speed <= 300.0

    profile = optimizer.generate_safe_trip_profile(max_depth_ft=6000.0, step_ft=2000.0)
    assert len(profile) == 3


def test_automated_well_control_kill_sheet():
    inputs = WellControlInput(
        current_mud_weight_ppg=11.2,
        true_vertical_depth_ft=11500.0,
        shut_in_drillpipe_pressure_psi=450.0,
        shut_in_casing_pressure_psi=680.0,
        slow_circulating_pressure_psi=750.0,
        pit_gain_bbl=18.5,
        casing_shoe_tvd_ft=9500.0,
        leak_off_test_emw_ppg=14.8,
    )
    engine = WellControlEngine(inputs)
    sheet = engine.generate_kill_sheet()

    # KMW = 11.2 + 450 / (0.052 * 11500) = 11.2 + 0.7525 = 11.95 ppg
    assert math.isclose(sheet.kill_mud_weight_ppg, 11.95, abs_tol=0.05)
    # ICP = 450 + 750 = 1200 psi
    assert math.isclose(sheet.initial_circulating_pressure_psi, 1200.0, abs_tol=1.0)
    # FCP = 750 * (11.95 / 11.2) = 800.2 psi
    assert math.isclose(sheet.final_circulating_pressure_psi, 800.2, abs_tol=2.0)
    assert sheet.initial_maasp_psi > 1500.0
    assert len(sheet.step_down_schedule) == 11
    assert sheet.step_down_schedule[0]["drillpipe_pressure_psi"] == sheet.initial_circulating_pressure_psi
    assert sheet.step_down_schedule[-1]["drillpipe_pressure_psi"] == sheet.final_circulating_pressure_psi


def test_mse_drilling_optimizer():
    optimizer = MSEDrillingOptimizer(bit_diameter_in=8.5)
    # Normal drilling
    diag = optimizer.diagnose_drilling_state(
        wob_klbf=18.0,
        surface_torque_ft_lbf=6500.0,
        surface_rpm=120.0,
        rate_of_penetration_ft_hr=85.0,
    )
    assert not diag["is_bit_balling"]
    assert not diag["is_stick_slip"]

    # Bit balling scenario: high WOB, very low ROP
    diag_balling = optimizer.diagnose_drilling_state(
        wob_klbf=35.0,
        surface_torque_ft_lbf=7000.0,
        surface_rpm=100.0,
        rate_of_penetration_ft_hr=6.0,
    )
    assert diag_balling["is_bit_balling"]
