"""Petroleum engineering kick precursor and rig anomaly detection module.

Couples physics-informed residual state estimation with well control signatures
to flag kicks, swab underbalance, washouts, and pack-offs before surface indicators register.
"""

from __future__ import annotations

import collections
from typing import Deque, Dict, List, Optional
from rig_twin.core.models import (
    AlertSeverity,
    AnomalyClassification,
    AnomalyDetectionResult,
    PhysicsBaseline,
    TelemetryRecord,
)
from rig_twin.ml.estimator import PhysicsResidualStateEstimator


class KickAndAnomalyDetector:
    """Continuous anomaly engine evaluating physics-residual vectors against well control physics."""

    def __init__(
        self,
        pore_pressure_ppg: float = 9.8,
        fracture_pressure_ppg: float = 14.5,
        kick_flow_threshold_gpm: float = 12.0,
        loss_flow_threshold_gpm: float = -12.0,
        consecutive_alarm_limit: int = 3,
    ):
        self.pore_pressure_ppg = pore_pressure_ppg
        self.fracture_pressure_ppg = fracture_pressure_ppg
        self.kick_flow_threshold_gpm = kick_flow_threshold_gpm
        self.loss_flow_threshold_gpm = loss_flow_threshold_gpm
        self.consecutive_alarm_limit = consecutive_alarm_limit

        self.estimator = PhysicsResidualStateEstimator()
        self.flow_kick_counter = 0
        self.loss_counter = 0
        self.packoff_counter = 0
        self.washout_counter = 0

    def evaluate(
        self, telemetry: TelemetryRecord, physics: PhysicsBaseline
    ) -> AnomalyDetectionResult:
        """Evaluate telemetry and physics baseline to identify downhole anomalies and kick precursors."""
        residuals, anomaly_score, metrics = self.estimator.step(telemetry, physics)

        spp_res = residuals["spp_residual"]
        flow_res = residuals["flow_residual"]
        ecd_res = residuals.get("ecd_residual", 0.0)
        pit_roc = telemetry.pit_rate_of_change_bbl_hr
        v_pipe = telemetry.string_velocity_ft_min

        # -------------------------------------------------------------
        # 1. Swab-Induced Kick Precursor Check (Tripping POOH)
        # -------------------------------------------------------------
        if v_pipe < -1.0:  # Pulling out of hole
            # Reset circulating counters during tripping
            self.flow_kick_counter = 0
            self.loss_counter = 0
            self.washout_counter = 0
            self.packoff_counter = 0

            eff_swab_ecd = physics.effective_ecd_swab_ppg
            if eff_swab_ecd < self.pore_pressure_ppg:
                severity = AlertSeverity.CRITICAL if eff_swab_ecd < (self.pore_pressure_ppg - 0.2) else AlertSeverity.WARNING
                return AnomalyDetectionResult(
                    timestamp=telemetry.timestamp,
                    well_id=telemetry.well_id,
                    measured_depth_ft=telemetry.measured_depth_ft,
                    classification=AnomalyClassification.SWAB_INDUCED_KICK_RISK,
                    severity=severity,
                    anomaly_score=max(0.85, anomaly_score),
                    spp_residual_psi=round(spp_res, 2),
                    flow_residual_gpm=round(flow_res, 2),
                    ecd_residual_ppg=round(ecd_res, 3),
                    pit_residual_bbl_min=round(pit_roc / 60.0, 3),
                    detection_rule="SWAB_UNDERBALANCE_LIMIT_EXCEEDED",
                    diagnostic_message=(
                        f"Swab pressure loss of {physics.swab_pressure_loss_psi:.1f} psi reduces "
                        f"effective ECD ({eff_swab_ecd:.2f} ppg) below formation pore pressure "
                        f"({self.pore_pressure_ppg:.2f} ppg) at tripping speed {abs(v_pipe):.1f} ft/min."
                    ),
                    recommended_action="Reduce pulling speed immediately; check hole fill volume and flow check.",
                    extra_features={"eff_swab_ecd": eff_swab_ecd, "pore_pressure": self.pore_pressure_ppg},
                )

        # -------------------------------------------------------------
        # 2. Surge-Induced Fracture Risk Check (Tripping RIH)
        # -------------------------------------------------------------
        if v_pipe > 1.0:  # Running into hole
            self.flow_kick_counter = 0
            self.loss_counter = 0
            self.washout_counter = 0
            self.packoff_counter = 0

            eff_surge_ecd = physics.effective_ecd_surge_ppg
            if eff_surge_ecd > self.fracture_pressure_ppg:
                return AnomalyDetectionResult(
                    timestamp=telemetry.timestamp,
                    well_id=telemetry.well_id,
                    measured_depth_ft=telemetry.measured_depth_ft,
                    classification=AnomalyClassification.SURGE_FRACTURE_RISK,
                    severity=AlertSeverity.CRITICAL,
                    anomaly_score=max(0.82, anomaly_score),
                    spp_residual_psi=round(spp_res, 2),
                    flow_residual_gpm=round(flow_res, 2),
                    ecd_residual_ppg=round(ecd_res, 3),
                    pit_residual_bbl_min=round(pit_roc / 60.0, 3),
                    detection_rule="SURGE_FRACTURE_LIMIT_EXCEEDED",
                    diagnostic_message=(
                        f"Surge pressure excess of {physics.surge_pressure_loss_psi:.1f} psi pushes "
                        f"effective ECD ({eff_surge_ecd:.2f} ppg) above formation fracture gradient "
                        f"({self.fracture_pressure_ppg:.2f} ppg)."
                    ),
                    recommended_action="Reduce running speed immediately to avoid formation breakdown / mud loss.",
                    extra_features={"eff_surge_ecd": eff_surge_ecd, "frac_pressure": self.fracture_pressure_ppg},
                )

        # Reset circulating counters when pumps are off
        if telemetry.flow_rate_in_gpm < 5.0:
            self.flow_kick_counter = 0
            self.loss_counter = 0
            self.washout_counter = 0
            self.packoff_counter = 0

        # -------------------------------------------------------------
        # 3. Kick Precursor Check (While Circulating / Drilling)
        # Pre-surface detection: positive delta flow + positive pit rate of change
        # -------------------------------------------------------------
        if flow_res > self.kick_flow_threshold_gpm or (metrics["flow_z"] > 2.5 and flow_res > 5.0):
            self.flow_kick_counter += 1
        else:
            self.flow_kick_counter = max(0, self.flow_kick_counter - 1)

        if self.flow_kick_counter >= self.consecutive_alarm_limit or (flow_res > 25.0 and pit_roc > 2.0):
            # Gas influx displacing mud typically causes slight SPP drop or downhole ECD drop
            severity = AlertSeverity.CRITICAL if (flow_res > 20.0 or pit_roc > 5.0) else AlertSeverity.WARNING
            score = min(1.0, max(0.88, anomaly_score + 0.15))
            return AnomalyDetectionResult(
                timestamp=telemetry.timestamp,
                well_id=telemetry.well_id,
                measured_depth_ft=telemetry.measured_depth_ft,
                classification=AnomalyClassification.KICK_PRECURSOR,
                severity=severity,
                anomaly_score=round(score, 3),
                spp_residual_psi=round(spp_res, 2),
                flow_residual_gpm=round(flow_res, 2),
                ecd_residual_ppg=round(ecd_res, 3),
                pit_residual_bbl_min=round(pit_roc / 60.0, 3),
                detection_rule="INFLUX_DELTA_FLOW_AND_PIT_RATE_ANOMALY",
                diagnostic_message=(
                    f"Kick precursor detected: Flow out exceeds flow in by {flow_res:.1f} gpm "
                    f"(z-score: {metrics['flow_z']:.2f}) with pit ROC of {pit_roc:.1f} bbl/hr. "
                    "Influx entering wellbore ahead of surface float switch alarm!"
                ),
                recommended_action="Execute immediate space-out, shut in pumps, perform flow check, prepare to close BOP.",
                extra_features={"consecutive_cycles": self.flow_kick_counter, "flow_z": metrics["flow_z"]},
            )

        # -------------------------------------------------------------
        # 4. Lost Circulation Detection
        # -------------------------------------------------------------
        if flow_res < self.loss_flow_threshold_gpm or (metrics["flow_z"] < -2.5 and flow_res < -8.0):
            self.loss_counter += 1
        else:
            self.loss_counter = max(0, self.loss_counter - 1)

        if self.loss_counter >= self.consecutive_alarm_limit:
            return AnomalyDetectionResult(
                timestamp=telemetry.timestamp,
                well_id=telemetry.well_id,
                measured_depth_ft=telemetry.measured_depth_ft,
                classification=AnomalyClassification.LOSS_CIRCULATION,
                severity=AlertSeverity.WARNING,
                anomaly_score=max(0.75, anomaly_score),
                spp_residual_psi=round(spp_res, 2),
                flow_residual_gpm=round(flow_res, 2),
                ecd_residual_ppg=round(ecd_res, 3),
                pit_residual_bbl_min=round(pit_roc / 60.0, 3),
                detection_rule="FLOW_OUT_DEFICIT_CIRCULATION_LOSS",
                diagnostic_message=(
                    f"Lost circulation event: Flow out deficit of {abs(flow_res):.1f} gpm "
                    f"and negative pit volume trend ({pit_roc:.1f} bbl/hr)."
                ),
                recommended_action="Reduce flow rate, monitor fluid level in annulus, prepare LCM pills.",
                extra_features={"loss_cycles": self.loss_counter},
            )

        # -------------------------------------------------------------
        # 5. Pack-off / Annular Restriction Incipient
        # SPP surging above theoretical physics, flow in constant, pit stable
        # -------------------------------------------------------------
        if spp_res > 120.0 and abs(flow_res) < 10.0 and pit_roc < 2.0:
            self.packoff_counter += 1
        else:
            self.packoff_counter = max(0, self.packoff_counter - 1)

        if self.packoff_counter >= self.consecutive_alarm_limit:
            return AnomalyDetectionResult(
                timestamp=telemetry.timestamp,
                well_id=telemetry.well_id,
                measured_depth_ft=telemetry.measured_depth_ft,
                classification=AnomalyClassification.PACK_OFF_INCIPIENT,
                severity=AlertSeverity.WARNING,
                anomaly_score=max(0.72, anomaly_score),
                spp_residual_psi=round(spp_res, 2),
                flow_residual_gpm=round(flow_res, 2),
                ecd_residual_ppg=round(ecd_res, 3),
                pit_residual_bbl_min=round(pit_roc / 60.0, 3),
                detection_rule="EXCESS_SPP_RESTRICTION",
                diagnostic_message=(
                    f"Incipient pack-off / hole cleaning issue: Standpipe pressure is {spp_res:.1f} psi "
                    "higher than hydraulics baseline with normal mass flow."
                ),
                recommended_action="Pick up off bottom, reduce RPM, verify cuttings returns on shale shakers.",
                extra_features={"packoff_cycles": self.packoff_counter},
            )

        # -------------------------------------------------------------
        # 6. Bit Nozzle Washout
        # SPP steadily lower than physics baseline, but flow balance and pit are normal
        # -------------------------------------------------------------
        if spp_res < -90.0 and abs(flow_res) < 8.0 and abs(pit_roc) < 1.5:
            self.washout_counter += 1
        else:
            self.washout_counter = max(0, self.washout_counter - 1)

        if self.washout_counter >= (self.consecutive_alarm_limit + 2):
            return AnomalyDetectionResult(
                timestamp=telemetry.timestamp,
                well_id=telemetry.well_id,
                measured_depth_ft=telemetry.measured_depth_ft,
                classification=AnomalyClassification.BIT_NOZZLE_WASHOUT,
                severity=AlertSeverity.WARNING,
                anomaly_score=max(0.68, anomaly_score),
                spp_residual_psi=round(spp_res, 2),
                flow_residual_gpm=round(flow_res, 2),
                ecd_residual_ppg=round(ecd_res, 3),
                pit_residual_bbl_min=round(pit_roc / 60.0, 3),
                detection_rule="STEADY_SPP_DROP_NORMAL_BALANCE",
                diagnostic_message=(
                    f"Potential bit nozzle washout or drillstring wash: SPP is {abs(spp_res):.1f} psi "
                    "below theoretical baseline with normal pit volume balance."
                ),
                recommended_action="Perform pump rate step test; inspect surface equipment; prepare to pull out of hole if wash confirmed.",
                extra_features={"washout_cycles": self.washout_counter},
            )

        # -------------------------------------------------------------
        # 7. Sensor Calibration Drift
        # -------------------------------------------------------------
        if abs(spp_res) > 50.0 and abs(metrics["spp_dev"]) < 10.0 and self.estimator.sample_count > 30:
            return AnomalyDetectionResult(
                timestamp=telemetry.timestamp,
                well_id=telemetry.well_id,
                measured_depth_ft=telemetry.measured_depth_ft,
                classification=AnomalyClassification.SENSOR_CALIBRATION_DRIFT,
                severity=AlertSeverity.INFO,
                anomaly_score=0.35,
                spp_residual_psi=round(spp_res, 2),
                flow_residual_gpm=round(flow_res, 2),
                ecd_residual_ppg=round(ecd_res, 3),
                pit_residual_bbl_min=round(pit_roc / 60.0, 3),
                detection_rule="STATIC_SYSTEMATIC_OFFSET",
                diagnostic_message=(
                    f"Steady static offset of {spp_res:.1f} psi detected between SPP sensor and physics model. "
                    "Likely zero-offset calibration drift on pressure transducer."
                ),
                recommended_action="Recalibrate standpipe pressure sensor zero point at next pump shutdown.",
                extra_features={"offset_psi": spp_res},
            )

        # -------------------------------------------------------------
        # 8. Normal Drilling State
        # -------------------------------------------------------------
        return AnomalyDetectionResult(
            timestamp=telemetry.timestamp,
            well_id=telemetry.well_id,
            measured_depth_ft=telemetry.measured_depth_ft,
            classification=AnomalyClassification.NORMAL,
            severity=AlertSeverity.INFO,
            anomaly_score=round(anomaly_score, 3),
            spp_residual_psi=round(spp_res, 2),
            flow_residual_gpm=round(flow_res, 2),
            ecd_residual_ppg=round(ecd_res, 3),
            pit_residual_bbl_min=round(pit_roc / 60.0, 3),
            detection_rule="WITHIN_PHYSICS_TOLERANCE",
            diagnostic_message="Telemetry closely tracks deterministic physics hydraulics baselines.",
            recommended_action=None,
            extra_features={},
        )
