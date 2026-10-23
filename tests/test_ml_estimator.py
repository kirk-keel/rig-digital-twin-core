"""Unit tests for ML state estimator and petroleum kick / anomaly detection."""

from datetime import datetime, timezone
import pytest
from rig_twin.core.models import (
    AlertSeverity,
    AnomalyClassification,
    PhysicsBaseline,
    TelemetryRecord,
)
from rig_twin.ml.estimator import KalmanResidualFilter, ResidualCusumDetector, PhysicsResidualStateEstimator
from rig_twin.ml.kick_detector import KickAndAnomalyDetector


def test_kalman_residual_filter_tracking():
    kf = KalmanResidualFilter(process_variance=1e-3, measurement_variance=2.0)
    # True bias is around 50.0 psi with noise
    estimates = []
    for _ in range(50):
        measurement = 50.0 + (pytest.importorskip("numpy").random.normal(0, 1.0))
        est = kf.update(measurement)
        estimates.append(est)

    # Filter should converge near 50.0
    assert abs(estimates[-1] - 50.0) < 2.0


def test_cusum_detector_shift():
    cusum = ResidualCusumDetector(threshold=3.0, drift=0.5)
    # Zero mean
    for _ in range(10):
        alarm, direction = cusum.update(0.1)
        assert not alarm

    # Sudden jump to +3.0 sigma
    alarm_fired = False
    for _ in range(5):
        alarm, direction = cusum.update(3.0)
        if alarm:
            alarm_fired = True
            assert direction == "HIGH"
            break
    assert alarm_fired


@pytest.fixture
def baseline_physics():
    return PhysicsBaseline(
        timestamp=datetime.now(timezone.utc),
        well_id="WELL-01",
        measured_depth_ft=10000.0,
        hydrostatic_pressure_psi=5200.0,
        annular_pressure_loss_psi=350.0,
        pipe_internal_pressure_loss_psi=1200.0,
        bit_pressure_loss_psi=1100.0,
        total_predicted_spp_psi=2700.0,
        static_ecd_ppg=10.0,
        dynamic_ecd_ppg=10.67,
        surge_pressure_loss_psi=0.0,
        swab_pressure_loss_psi=0.0,
        effective_ecd_surge_ppg=10.67,
        effective_ecd_swab_ppg=10.67,
        annulus_flow_regime="LAMINAR",
        pipe_flow_regime="TURBULENT",
        bit_jet_impact_force_lbf=600.0,
        bit_hydraulic_horsepower_hhp=350.0,
    )


def test_kick_precursor_detection(baseline_physics):
    detector = KickAndAnomalyDetector(consecutive_alarm_limit=2)
    t = datetime.now(timezone.utc)

    # Influx: flow out > flow in (+20 gpm), pit rate of change positive
    record = TelemetryRecord(
        timestamp=t,
        well_id="WELL-01",
        measured_depth_ft=10000.0,
        true_vertical_depth_ft=10000.0,
        bit_depth_ft=10000.0,
        hole_depth_ft=10000.0,
        flow_rate_in_gpm=500.0,
        flow_rate_out_gpm=525.0,  # +25 gpm delta flow
        standpipe_pressure_psi=2690.0,
        pit_rate_of_change_bbl_hr=6.0,
    )

    # Cycle 1
    res1 = detector.evaluate(record, baseline_physics)
    # Cycle 2 -> triggers alarm
    res2 = detector.evaluate(record, baseline_physics)

    assert res2.classification == AnomalyClassification.KICK_PRECURSOR
    assert res2.severity in [AlertSeverity.CRITICAL, AlertSeverity.WARNING]
    assert res2.anomaly_score >= 0.8


def test_swab_risk_detection(baseline_physics):
    detector = KickAndAnomalyDetector(pore_pressure_ppg=10.2)
    t = datetime.now(timezone.utc)

    # Update physics with swab pressure loss: dynamic ECD = 10.0 - 0.5 = 9.5 ppg < 10.2 ppg
    baseline_physics.swab_pressure_loss_psi = 180.0
    baseline_physics.effective_ecd_swab_ppg = 9.65

    # Tripping out at -120 ft/min
    record = TelemetryRecord(
        timestamp=t,
        well_id="WELL-01",
        measured_depth_ft=10000.0,
        true_vertical_depth_ft=10000.0,
        bit_depth_ft=10000.0,
        hole_depth_ft=10000.0,
        string_velocity_ft_min=-120.0,
        flow_rate_in_gpm=0.0,
        flow_rate_out_gpm=0.0,
        standpipe_pressure_psi=0.0,
    )

    res = detector.evaluate(record, baseline_physics)
    assert res.classification == AnomalyClassification.SWAB_INDUCED_KICK_RISK
    assert res.severity == AlertSeverity.CRITICAL


def test_lost_circulation_detection(baseline_physics):
    detector = KickAndAnomalyDetector(consecutive_alarm_limit=2)
    t = datetime.now(timezone.utc)

    # Loss: flow out deficit (-20 gpm)
    record = TelemetryRecord(
        timestamp=t,
        well_id="WELL-01",
        measured_depth_ft=10000.0,
        true_vertical_depth_ft=10000.0,
        bit_depth_ft=10000.0,
        hole_depth_ft=10000.0,
        flow_rate_in_gpm=500.0,
        flow_rate_out_gpm=475.0,  # -25 gpm loss
        standpipe_pressure_psi=2650.0,
        pit_rate_of_change_bbl_hr=-8.0,
    )

    detector.evaluate(record, baseline_physics)
    res = detector.evaluate(record, baseline_physics)
    assert res.classification == AnomalyClassification.LOSS_CIRCULATION
