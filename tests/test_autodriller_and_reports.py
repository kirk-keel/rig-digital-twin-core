"""Unit tests for AutoDriller setpoint advisory, WITS0 stream parsing, and Incident Reports."""

import asyncio
from datetime import datetime, timezone
import pytest

from rig_twin.core.models import (
    AlertSeverity,
    AnomalyClassification,
    AnomalyDetectionResult,
    PhysicsBaseline,
    TelemetryRecord,
)
from rig_twin.core.report_exporter import IncidentReportExporter
from rig_twin.ingestion.wits0_parser import Wits0Parser, Wits0TcpServer
from rig_twin.ml.autodriller import AutoDrillerAdvisory


@pytest.fixture
def sample_telemetry_and_physics():
    now = datetime.now(timezone.utc)
    t = TelemetryRecord(
        timestamp=now,
        well_id="WELL-ALPHA",
        measured_depth_ft=11450.0,
        true_vertical_depth_ft=11450.0,
        bit_depth_ft=11450.0,
        hole_depth_ft=11450.0,
        flow_rate_in_gpm=520.0,
        flow_rate_out_gpm=520.0,
        standpipe_pressure_psi=4085.0,
        surface_rpm=120.0,
        surface_torque_ft_lbf=6500.0,
        mud_weight_in_ppg=11.2,
    )
    p = PhysicsBaseline(
        timestamp=now,
        well_id="WELL-ALPHA",
        measured_depth_ft=11450.0,
        hydrostatic_pressure_psi=6669.0,
        annular_pressure_loss_psi=350.0,
        pipe_internal_pressure_loss_psi=1900.0,
        bit_pressure_loss_psi=1500.0,
        total_predicted_spp_psi=4085.0,
        static_ecd_ppg=11.2,
        dynamic_ecd_ppg=11.78,
        surge_pressure_loss_psi=0.0,
        swab_pressure_loss_psi=0.0,
        effective_ecd_surge_ppg=11.78,
        effective_ecd_swab_ppg=11.78,
        annulus_flow_regime="LAMINAR",
        pipe_flow_regime="TURBULENT",
        bit_jet_impact_force_lbf=800.0,
        bit_hydraulic_horsepower_hhp=450.0,
    )
    return t, p


def test_autodriller_advisory(sample_telemetry_and_physics):
    telemetry, physics = sample_telemetry_and_physics
    advisory = AutoDrillerAdvisory()

    # Steady state
    rec_steady = advisory.evaluate_setpoints(telemetry, physics, rate_of_penetration_ft_hr=75.0, current_wob_klbf=20.0)
    assert rec_steady.recommended_wob_klbf > 0.0
    assert rec_steady.recommended_rpm > 0.0

    # Stick-slip mitigation scenario: high torque variation (> 35%)
    rec_ss = advisory.evaluate_setpoints(telemetry, physics, rate_of_penetration_ft_hr=60.0, current_wob_klbf=25.0, torque_std_dev=2800.0)
    assert rec_ss.optimization_strategy == "MITIGATE_STICK_SLIP"
    assert rec_ss.constraints_active["stick_slip_active"]
    assert rec_ss.recommended_rpm > telemetry.surface_rpm

    # ECD margin restriction scenario: dynamic ECD approaches fracture gradient
    rec_ecd = advisory.evaluate_setpoints(telemetry, physics, fracture_pressure_ppg=12.0)
    assert rec_ecd.optimization_strategy == "MANAGE_ECD_PRESSURE_WINDOW"
    assert rec_ecd.recommended_flow_rate_gpm < telemetry.flow_rate_in_gpm


def test_wits0_parser():
    sample_packet = (
        "&&\r\n"
        "010811450.5\r\n"
        "010911450.5\r\n"
        "01104085.0\r\n"
        "0112520.0\r\n"
        "0113525.0\r\n"
        "0114120.0\r\n"
        "01158500.0\r\n"
        "0116245.0\r\n"
        "120811.20\r\n"
        "1210520.0\r\n"
        "!!\r\n"
    )
    parsed = Wits0Parser.parse_packet(sample_packet, well_id="RIG-BRAVO")
    assert parsed is not None
    assert parsed.well_id == "RIG-BRAVO"
    assert parsed.bit_depth_ft == 11450.5
    assert parsed.standpipe_pressure_psi == 4085.0
    assert parsed.delta_flow_gpm == 5.0

    # Test formatter
    re_encoded = Wits0Parser.format_packet(parsed)
    assert "010811450.50" in re_encoded
    assert "01104085.0" in re_encoded


def test_incident_report_exporter(sample_telemetry_and_physics):
    telemetry, physics = sample_telemetry_and_physics
    anomaly = AnomalyDetectionResult(
        timestamp=datetime.now(timezone.utc),
        well_id="WELL-ALPHA",
        measured_depth_ft=11450.0,
        classification=AnomalyClassification.KICK_PRECURSOR,
        severity=AlertSeverity.CRITICAL,
        anomaly_score=0.92,
        spp_residual_psi=-18.0,
        flow_residual_gpm=24.5,
        detection_rule="INFLUX_DELTA_FLOW_AND_PIT_RATE_ANOMALY",
        diagnostic_message="Critical influx precursor detected ahead of surface tank float alarms.",
        recommended_action="Execute immediate space-out, shut in pumps, verify flow check.",
    )

    dossier = IncidentReportExporter.generate_report(anomaly, telemetry, physics)
    assert "INC-WELL-ALPHA-" in dossier["incident_id"]
    assert "# WELL INCIDENT AUDIT DOSSIER" in dossier["markdown"]
    assert "KICK_PRECURSOR" in dossier["markdown"]
    assert "Automated Well Control Kill Solution" in dossier["markdown"]
    assert dossier["payload"]["kill_sheet"] is not None
