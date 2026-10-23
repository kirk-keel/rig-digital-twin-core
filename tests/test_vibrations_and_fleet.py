"""Unit tests for BHA Vibrations, Waterhammer, Casing Wear, Fleet Orchestrator, and What-If Sandbox."""

from datetime import datetime, timezone
import pytest
from starlette.testclient import TestClient

from rig_twin.demo import build_sample_well
from rig_twin.core.fleet import FleetManager
from rig_twin.core.models import TelemetryRecord
from rig_twin.physics.casing_wear import CasingWearAndFatigueEngine
from rig_twin.physics.transient_hydraulics import TransientHydraulicsEngine
from rig_twin.physics.vibrations import DrillstringDynamicsEngine
from rig_twin.physics.what_if_sandbox import WhatIfSandbox
from rig_twin.server.api import app


def test_drillstring_vibrations_and_whirl():
    engine = DrillstringDynamicsEngine(drillstring_length_ft=11450.0, stabilizer_spacing_ft=60.0)
    eval_res = engine.evaluate_safe_operating_rpm_bands()

    assert eval_res.axial_bit_bounce_natural_freq_hz > 0.0
    assert eval_res.torsional_stick_slip_natural_freq_hz > 0.0
    assert eval_res.forward_whirl_critical_rpm > 50.0
    assert eval_res.backward_whirl_critical_rpm < eval_res.forward_whirl_critical_rpm
    assert len(eval_res.resonance_bands) > 0
    assert len(eval_res.safe_rpm_windows) > 0


def test_transient_waterhammer_surge():
    well, fluid = build_sample_well()
    engine = TransientHydraulicsEngine(fluid=fluid, well_depth_ft=11450.0)

    # Rapid closure (0.2 sec < round trip time ~5.7s)
    res_rapid = engine.simulate_valve_closure_surge(flow_rate_gpm=520.0, valve_closure_time_sec=0.2)
    assert res_rapid.is_rapid_closure
    assert res_rapid.joukowsky_peak_surge_psi > 200.0
    assert res_rapid.total_transient_peak_pressure_psi > 4085.0
    assert len(res_rapid.wave_pressure_profile) > 10

    # Gradual closure (10.0 sec > round trip time)
    res_gradual = engine.simulate_valve_closure_surge(flow_rate_gpm=520.0, valve_closure_time_sec=10.0)
    assert not res_gradual.is_rapid_closure
    assert res_gradual.effective_surge_pressure_psi < res_rapid.effective_surge_pressure_psi


def test_casing_wear_and_fatigue():
    engine = CasingWearAndFatigueEngine()
    
    # Casing wear
    wear = engine.calculate_casing_wear(depth_ft=8000.0, contact_force_lbf=1500.0, dogleg_deg_100ft=3.0, rotating_hours=80.0)
    assert wear.wear_groove_depth_in > 0.0
    assert wear.remaining_wall_thickness_in < wear.nominal_wall_thickness_in
    assert wear.derated_burst_psi < wear.nominal_burst_psi
    assert wear.derated_collapse_psi < wear.nominal_collapse_psi

    # Drillpipe fatigue in dogleg
    fatigue = engine.calculate_drillpipe_fatigue(depth_ft=8000.0, dogleg_deg_100ft=4.5, rotating_hours=100.0)
    assert fatigue.bending_stress_psi > 4000.0
    assert fatigue.fatigue_damage_index > 0.0


def test_fleet_orchestrator():
    well1, fluid1 = build_sample_well()
    well1.well_id = "RIG-FLEET-01"

    well2, fluid2 = build_sample_well()
    well2.well_id = "RIG-FLEET-02"

    fleet = FleetManager()
    fleet.register_well(well1, fluid1)
    fleet.register_well(well2, fluid2)

    # Route telemetry for well 1
    t1 = TelemetryRecord(
        timestamp=datetime.now(timezone.utc),
        well_id="RIG-FLEET-01",
        measured_depth_ft=10500.0,
        true_vertical_depth_ft=10500.0,
        bit_depth_ft=10500.0,
        hole_depth_ft=10500.0,
        flow_rate_in_gpm=500.0,
        flow_rate_out_gpm=500.0,
        standpipe_pressure_psi=3800.0,
    )
    fleet.process_telemetry(t1)

    summaries = fleet.get_fleet_summary()
    assert len(summaries) == 1
    assert summaries[0].well_id == "RIG-FLEET-01"
    assert summaries[0].measured_depth_ft == 10500.0


def test_what_if_sandbox():
    well, fluid = build_sample_well()
    tel = TelemetryRecord(
        timestamp=datetime.now(timezone.utc),
        well_id=well.well_id,
        measured_depth_ft=11450.0,
        true_vertical_depth_ft=11450.0,
        bit_depth_ft=11450.0,
        hole_depth_ft=11450.0,
        flow_rate_in_gpm=520.0,
        flow_rate_out_gpm=520.0,
        standpipe_pressure_psi=4085.0,
    )
    sandbox = WhatIfSandbox(well, fluid, tel)

    # Test flow step test
    res_flow = sandbox.simulate_flow_rate_step(target_flow_gpm=600.0)
    assert res_flow.predicted_spp_psi > 4085.0

    # Test mud weight change
    res_mw = sandbox.simulate_mud_weight_change(target_mud_weight_ppg=11.6)
    assert res_mw.predicted_ecd_ppg > 11.6

    # Test tripping speed change
    res_trip = sandbox.simulate_tripping_speed(target_velocity_ft_min=-120.0)
    assert "POOH" in res_trip.engineering_insights


def test_api_new_endpoints():
    with TestClient(app) as client:
        # BHA Vibrations
        res_vib = client.get("/api/vibrations/bha")
        assert res_vib.status_code == 200
        assert "forward_whirl_critical_rpm" in res_vib.json()

        # Waterhammer
        res_wh = client.get("/api/transient/waterhammer?flow_gpm=520&closure_sec=0.5")
        assert res_wh.status_code == 200
        assert "joukowsky_peak_surge_psi" in res_wh.json()

        # Casing Wear
        res_wear = client.get("/api/casing/wear?depth_ft=8500&hours=72")
        assert res_wear.status_code == 200
        assert "casing_wear" in res_wear.json()

        # Fleet Summary
        res_fleet = client.get("/api/fleet/summary")
        assert res_fleet.status_code == 200
        assert "fleet" in res_fleet.json()

        # What-If Simulate
        res_whatif = client.post("/api/what-if/simulate?scenario_type=FLOW_STEP&target_value=580")
        assert res_whatif.status_code == 200
        assert "predicted_spp_psi" in res_whatif.json()
