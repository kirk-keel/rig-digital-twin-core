"""Machine learning state estimation, kick detection, auto-calibration, and auto-driller advisory."""

from rig_twin.ml.estimator import (
    KalmanResidualFilter,
    ResidualCusumDetector,
    PhysicsResidualStateEstimator,
)
from rig_twin.ml.kick_detector import KickAndAnomalyDetector
from rig_twin.ml.auto_calibrator import OnlineParameterCalibrator
from rig_twin.ml.autodriller import (
    AutoDrillerAdvisory,
    AutoDrillerSetpointRecommendation,
)

__all__ = [
    "KalmanResidualFilter",
    "ResidualCusumDetector",
    "PhysicsResidualStateEstimator",
    "KickAndAnomalyDetector",
    "OnlineParameterCalibrator",
    "AutoDrillerAdvisory",
    "AutoDrillerSetpointRecommendation",
]
