"""Physics-Informed ML Residual State Estimator.

Tracks residuals between deterministic petroleum engineering physics and real-time
telemetry to distinguish systematic baseline drift from abrupt downhole anomalies.
"""

from __future__ import annotations

import collections
import math
from typing import Dict, List, Optional, Tuple
import numpy as np
from sklearn.ensemble import IsolationForest

from rig_twin.core.models import (
    AlertSeverity,
    AnomalyClassification,
    AnomalyDetectionResult,
    PhysicsBaseline,
    TelemetryRecord,
)


class KalmanResidualFilter:
    """1D Recursive Kalman Filter for online tracking of steady-state physics residuals.
    
    State x represents the current expected residual bias (e.g. due to cuttings bed friction).
    """

    def __init__(self, process_variance: float = 1e-4, measurement_variance: float = 4.0):
        self.q = process_variance
        self.r = measurement_variance
        self.x = 0.0  # Estimated residual state
        self.p = 1.0  # Estimation error covariance
        self.k = 0.0  # Kalman gain
        self.initialized = False

    def update(self, measurement: float) -> float:
        """Update filter with new raw residual measurement, returns filtered estimate."""
        if not self.initialized:
            self.x = measurement
            self.p = self.r
            self.initialized = True
            return self.x

        # Time update (prediction)
        p_prior = self.p + self.q

        # Measurement update (correction)
        self.k = p_prior / (p_prior + self.r)
        self.x = self.x + self.k * (measurement - self.x)
        self.p = (1.0 - self.k) * p_prior

        return self.x


class ResidualCusumDetector:
    """Two-sided Cumulative Sum (CUSUM) change-point detector on residuals."""

    def __init__(self, threshold: float = 4.0, drift: float = 0.5):
        self.threshold = threshold
        self.drift = drift
        self.s_pos = 0.0
        self.s_neg = 0.0

    def update(self, residual_zscore: float) -> Tuple[bool, str]:
        """Update CUSUM with normalized residual z-score.
        
        Returns (is_alarm, direction: "HIGH"|"LOW"|"NORMAL").
        """
        self.s_pos = max(0.0, self.s_pos + residual_zscore - self.drift)
        self.s_neg = max(0.0, self.s_neg - residual_zscore - self.drift)

        if self.s_pos > self.threshold:
            self.s_pos = 0.0
            return True, "HIGH"
        elif self.s_neg > self.threshold:
            self.s_neg = 0.0
            return True, "LOW"
        return False, "NORMAL"


class PhysicsResidualStateEstimator:
    """Coupled Physics-ML state estimator and multivariate residual anomaly engine.
    
    Inductive bias:
        y_obs = f_physics(X) + f_ml_residual(X) + epsilon
    """

    def __init__(
        self,
        window_size: int = 60,
        isolation_forest_enabled: bool = True,
    ):
        self.window_size = window_size
        self.use_iso_forest = isolation_forest_enabled

        # Kalman filters for tracking steady-state residual baselines
        self.kf_spp = KalmanResidualFilter(process_variance=1e-3, measurement_variance=9.0)
        self.kf_flow = KalmanResidualFilter(process_variance=1e-3, measurement_variance=4.0)
        self.kf_ecd = KalmanResidualFilter(process_variance=1e-4, measurement_variance=0.01)

        # CUSUM detectors for transient change detection
        self.cusum_spp = ResidualCusumDetector(threshold=4.5, drift=0.6)
        self.cusum_flow = ResidualCusumDetector(threshold=3.5, drift=0.5)

        # Sliding window history of residual vectors: [spp_res, flow_res, ecd_res, pit_roc]
        self.residual_history: collections.deque = collections.deque(maxlen=window_size)
        self.baseline_stats: Dict[str, Dict[str, float]] = {
            "spp": {"mean": 0.0, "std": 15.0},
            "flow": {"mean": 0.0, "std": 8.0},
            "ecd": {"mean": 0.0, "std": 0.05},
        }

        # Warm-up tracking
        self.sample_count = 0
        self.iso_forest: Optional[IsolationForest] = None

    def compute_residuals(
        self, telemetry: TelemetryRecord, physics: PhysicsBaseline
    ) -> Dict[str, float]:
        """Compute instantaneous residuals between observed telemetry and physics baseline."""
        # SPP residual = observed SPP - theoretical SPP
        spp_res = telemetry.standpipe_pressure_psi - physics.total_predicted_spp_psi

        # Flow residual = observed flow out - observed flow in
        flow_res = telemetry.delta_flow_gpm

        # ECD residual (if PWD downhole sensor is active)
        ecd_res: Optional[float] = None
        if telemetry.downhole_ecd_ppg is not None:
            ecd_res = telemetry.downhole_ecd_ppg - physics.dynamic_ecd_ppg
        elif telemetry.downhole_annular_pressure_psi is not None and telemetry.true_vertical_depth_ft > 0:
            obs_ecd = telemetry.downhole_annular_pressure_psi / (0.052 * telemetry.true_vertical_depth_ft)
            ecd_res = obs_ecd - physics.dynamic_ecd_ppg

        return {
            "spp_residual": spp_res,
            "flow_residual": flow_res,
            "ecd_residual": ecd_res if ecd_res is not None else 0.0,
            "pit_roc": telemetry.pit_rate_of_change_bbl_hr,
        }

    def _update_baseline_stats(self) -> None:
        """Recalculate running statistical moments from the sliding history window."""
        if len(self.residual_history) < 10:
            return

        arr = np.array(self.residual_history)
        spp_vals = arr[:, 0]
        flow_vals = arr[:, 1]
        ecd_vals = arr[:, 2]

        self.baseline_stats["spp"] = {
            "mean": float(np.mean(spp_vals)),
            "std": max(float(np.std(spp_vals)), 2.0),
        }
        self.baseline_stats["flow"] = {
            "mean": float(np.mean(flow_vals)),
            "std": max(float(np.std(flow_vals)), 1.5),
        }
        self.baseline_stats["ecd"] = {
            "mean": float(np.mean(ecd_vals)),
            "std": max(float(np.std(ecd_vals)), 0.01),
        }

    def step(
        self, telemetry: TelemetryRecord, physics: PhysicsBaseline
    ) -> Tuple[Dict[str, float], float, Dict[str, Any]]:
        """Process one time-step: update Kalman filters, CUSUM, and compute anomaly score."""
        self.sample_count += 1
        residuals = self.compute_residuals(telemetry, physics)

        spp_res = residuals["spp_residual"]
        flow_res = residuals["flow_residual"]
        ecd_res = residuals["ecd_residual"]

        # Filtered residual baseline
        spp_base = self.kf_spp.update(spp_res)
        flow_base = self.kf_flow.update(flow_res)
        ecd_base = self.kf_ecd.update(ecd_res)

        # Deviation from filtered baseline (high-frequency anomaly deviation)
        spp_dev = spp_res - spp_base
        flow_dev = flow_res - flow_base

        # Standardized z-scores
        spp_z = spp_dev / self.baseline_stats["spp"]["std"]
        flow_z = flow_dev / self.baseline_stats["flow"]["std"]

        # CUSUM updates
        cusum_spp_alarm, cusum_spp_dir = self.cusum_spp.update(spp_z)
        cusum_flow_alarm, cusum_flow_dir = self.cusum_flow.update(flow_z)

        # Append feature vector to window
        vector = [spp_res, flow_res, ecd_res, telemetry.pit_rate_of_change_bbl_hr]
        self.residual_history.append(vector)

        if self.sample_count % 15 == 0:
            self._update_baseline_stats()

        # Multivariate anomaly score via Mahalanobis-like residual norm
        norm_spp = (abs(spp_dev) / self.baseline_stats["spp"]["std"]) ** 2
        norm_flow = (abs(flow_dev) / self.baseline_stats["flow"]["std"]) ** 2
        norm_pit = (abs(telemetry.pit_rate_of_change_bbl_hr) / 3.0) ** 2

        raw_dist = math.sqrt(norm_spp + norm_flow + norm_pit)
        # Sigmoid squash to [0.0, 1.0]
        anomaly_score = float(1.0 / (1.0 + math.exp(-0.7 * (raw_dist - 3.0))))

        metrics = {
            "spp_dev": spp_dev,
            "flow_dev": flow_dev,
            "spp_z": spp_z,
            "flow_z": flow_z,
            "cusum_spp_alarm": cusum_spp_alarm,
            "cusum_spp_dir": cusum_spp_dir,
            "cusum_flow_alarm": cusum_flow_alarm,
            "cusum_flow_dir": cusum_flow_dir,
            "raw_dist": raw_dist,
        }

        return residuals, anomaly_score, metrics
