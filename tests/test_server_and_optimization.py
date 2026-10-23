"""Unit tests for ML auto-calibrator and FastAPI REST/WebSocket endpoints."""

from datetime import datetime, timezone
import pytest
from starlette.testclient import TestClient
from rig_twin.ml.auto_calibrator import OnlineParameterCalibrator
from rig_twin.server.api import app


def test_online_parameter_calibrator():
    calibrator = OnlineParameterCalibrator(initial_annulus_f_mult=1.0, initial_pipe_f_mult=1.0)
    
    # Simulate steady drilling with observed SPP higher than physics model (+120 psi bias)
    for _ in range(15):
        params = calibrator.update(
            predicted_spp_psi=3800.0,
            observed_spp_psi=3920.0,
            predicted_apl_psi=350.0,
            observed_apl_psi=390.0,
            pipe_loss_psi=1800.0,
            is_steady_drilling=True,
        )

    # Multipliers should increase to compensate for higher friction
    assert params["annulus_friction_factor_multiplier"] > 1.0
    assert params["pipe_friction_factor_multiplier"] > 1.0
    assert params["total_calibration_updates"] == 15


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_api_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "well_id" in data


def test_api_dashboard_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "RIG DIGITAL TWIN CORE" in res.text
    assert "AUTOMATED KILL SHEET" in res.text


def test_api_well_config(client):
    res = client.get("/api/well")
    assert res.status_code == 200
    data = res.json()
    assert "well" in data
    assert "fluid" in data


def test_api_safe_trip_envelope(client):
    res = client.get("/api/safe-trip-envelope")
    assert res.status_code == 200
    data = res.json()
    assert "envelope" in data
    assert len(data["envelope"]) > 0
    assert "max_safe_pooh_speed_ft_min" in data["envelope"][0]


def test_api_well_control_kill_sheet(client):
    payload = {
        "well_id": "TEST-WELL",
        "current_mud_weight_ppg": 11.2,
        "true_vertical_depth_ft": 11500.0,
        "shut_in_drillpipe_pressure_psi": 450.0,
        "shut_in_casing_pressure_psi": 680.0,
        "slow_circulating_pressure_psi": 750.0,
        "pit_gain_bbl": 18.5,
    }
    res = client.post("/api/well-control/kill-sheet", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["kill_mud_weight_ppg"] > 11.2
    assert "step_down_schedule" in data


def test_api_broomstick(client):
    res = client.get("/api/torque-drag/broomstick")
    assert res.status_code == 200
    data = res.json()
    assert "broomstick_curves" in data
    assert len(data["broomstick_curves"]) > 0


def test_api_telemetry_ingest(client):
    telemetry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "well_id": "NORTH-SEA-APEX-01",
        "measured_depth_ft": 11450.0,
        "true_vertical_depth_ft": 11450.0,
        "bit_depth_ft": 11450.0,
        "hole_depth_ft": 11450.0,
        "flow_rate_in_gpm": 520.0,
        "flow_rate_out_gpm": 520.0,
        "standpipe_pressure_psi": 4085.0,
    }
    res = client.post("/api/telemetry/ingest", json=telemetry)
    assert res.status_code == 200
    data = res.json()
    assert "physics" in data
    assert "anomaly" in data
    assert data["anomaly"]["classification"] == "NORMAL"


def test_api_websocket_stream(client):
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text("ping")
        resp = ws.receive_text()
        assert resp == "pong"
