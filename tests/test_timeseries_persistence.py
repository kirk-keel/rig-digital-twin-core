"""Unit tests for TimescaleDB repository, ORM schemas, and time-series logging."""

from datetime import datetime, timezone
import pytest
from rig_twin.core.models import (
    AlertSeverity,
    AnomalyClassification,
    AnomalyDetectionResult,
    PhysicsBaseline,
    TelemetryRecord,
)
from rig_twin.persistence.repository import TimescaleTwinRepository


@pytest.fixture
def repo():
    r = TimescaleTwinRepository("sqlite:///:memory:")
    r.initialize_schema()
    return r


def test_log_and_query_telemetry(repo):
    t = datetime.now(timezone.utc)
    rec = TelemetryRecord(
        timestamp=t,
        well_id="WELL-PERSIST-1",
        measured_depth_ft=5000.0,
        true_vertical_depth_ft=5000.0,
        bit_depth_ft=5000.0,
        hole_depth_ft=5000.0,
        flow_rate_in_gpm=450.0,
        flow_rate_out_gpm=450.0,
        standpipe_pressure_psi=2100.0,
    )

    repo.log_telemetry_batch([rec])
    results = repo.get_recent_telemetry(well_id="WELL-PERSIST-1", limit=10)
    assert len(results) == 1
    assert results[0].standpipe_pressure_psi == 2100.0
    assert results[0].well_id == "WELL-PERSIST-1"


def test_log_and_query_physics(repo):
    t = datetime.now(timezone.utc)
    phys = PhysicsBaseline(
        timestamp=t,
        well_id="WELL-PERSIST-1",
        measured_depth_ft=5000.0,
        hydrostatic_pressure_psi=2600.0,
        annular_pressure_loss_psi=150.0,
        pipe_internal_pressure_loss_psi=800.0,
        bit_pressure_loss_psi=600.0,
        total_predicted_spp_psi=1580.0,
        static_ecd_ppg=10.0,
        dynamic_ecd_ppg=10.58,
        surge_pressure_loss_psi=0.0,
        swab_pressure_loss_psi=0.0,
        effective_ecd_surge_ppg=10.58,
        effective_ecd_swab_ppg=10.58,
        annulus_flow_regime="LAMINAR",
        pipe_flow_regime="TURBULENT",
        bit_jet_impact_force_lbf=400.0,
        bit_hydraulic_horsepower_hhp=200.0,
    )

    repo.log_physics_batch([phys])


def test_log_and_query_anomalies(repo):
    t = datetime.now(timezone.utc)
    anom = AnomalyDetectionResult(
        timestamp=t,
        well_id="WELL-PERSIST-1",
        measured_depth_ft=5000.0,
        classification=AnomalyClassification.KICK_PRECURSOR,
        severity=AlertSeverity.CRITICAL,
        anomaly_score=0.92,
        spp_residual_psi=-15.0,
        flow_residual_gpm=22.0,
        detection_rule="INFLUX_RULE",
        diagnostic_message="Critical influx precursor detected",
        recommended_action="Shut-in pumps",
    )

    repo.log_anomaly_batch([anom])
    anomalies = repo.get_recent_anomalies("WELL-PERSIST-1", severity="CRITICAL")
    assert len(anomalies) == 1
    assert anomalies[0].classification == "KICK_PRECURSOR"
    assert anomalies[0].anomaly_score == 0.92
