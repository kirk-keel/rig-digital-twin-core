"""Online Bayesian parameter auto-calibration engine for drilling hydraulics.

Recursively estimates downhole annular friction factor multipliers and drillpipe
roughness from streaming PWD downhole annular pressure and surface SPP observations.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple
import numpy as np


class OnlineParameterCalibrator:
    """Recursive Bayesian parameter estimator updating hydraulics parameters in real-time."""

    def __init__(
        self,
        initial_annulus_f_mult: float = 1.0,
        initial_pipe_f_mult: float = 1.0,
        learning_rate: float = 0.02,
        min_f_mult: float = 0.70,
        max_f_mult: float = 1.60,
    ):
        # State vector theta = [annulus_multiplier, pipe_multiplier]
        self.theta = np.array([initial_annulus_f_mult, initial_pipe_f_mult], dtype=float)
        # Covariance matrix P
        self.P = np.diag([0.05, 0.05])
        # Process noise covariance Q (slow parameter drift)
        self.Q = np.diag([1e-5, 1e-5])
        # Measurement noise covariance R (sensor variance)
        self.R = np.diag([25.0, 4.0])  # SPP noise var ~25 psi², PWD noise var ~4 psi²

        self.lr = learning_rate
        self.min_f_mult = min_f_mult
        self.max_f_mult = max_f_mult
        self.updates_count = 0

    def update(
        self,
        predicted_spp_psi: float,
        observed_spp_psi: float,
        predicted_apl_psi: float,
        observed_apl_psi: Optional[float] = None,
        pipe_loss_psi: float = 1200.0,
        is_steady_drilling: bool = True,
    ) -> Dict[str, float]:
        """Perform recursive update if drilling is in a steady state (not kicking or tripping)."""
        if not is_steady_drilling or observed_spp_psi <= 50.0:
            return self.get_parameters()

        # Measurement residual vector: y - h(theta)
        # SPP depends on both pipe friction and annular friction
        spp_error = observed_spp_psi - predicted_spp_psi

        # Jacobian H: partial derivatives d(SPP)/d(theta_ann), d(SPP)/d(theta_pipe)
        # d(SPP)/d(theta_ann) ≈ predicted_apl_psi
        # d(SPP)/d(theta_pipe) ≈ pipe_loss_psi
        h_ann = max(predicted_apl_psi, 10.0)
        h_pipe = max(pipe_loss_psi, 10.0)

        # Time update (Prediction)
        P_prior = self.P + self.Q

        if observed_apl_psi is not None:
            # 2D observation: [SPP, PWD_APL]
            apl_error = observed_apl_psi - predicted_apl_psi
            residuals = np.array([spp_error, apl_error])
            H = np.array([
                [h_ann, h_pipe],
                [h_ann, 0.0]
            ])
            S = H @ P_prior @ H.T + self.R
            K = P_prior @ H.T @ np.linalg.inv(S)
            d_theta = K @ residuals
            self.P = (np.eye(2) - K @ H) @ P_prior
        else:
            # 1D observation: SPP only
            H_1d = np.array([[h_ann, h_pipe]])
            S_1d = float(H_1d @ P_prior @ H_1d.T + self.R[0, 0])
            K_1d = (P_prior @ H_1d.T) / S_1d
            d_theta = (K_1d * spp_error).flatten()
            self.P = (np.eye(2) - K_1d @ H_1d) @ P_prior

        # Damped state update
        self.theta = self.theta + (self.lr * d_theta)

        # Enforce physical bounds
        self.theta[0] = min(max(self.theta[0], self.min_f_mult), self.max_f_mult)
        self.theta[1] = min(max(self.theta[1], self.min_f_mult), self.max_f_mult)
        self.updates_count += 1

        return self.get_parameters()

    def get_parameters(self) -> Dict[str, float]:
        """Return currently estimated parameter values."""
        return {
            "annulus_friction_factor_multiplier": round(float(self.theta[0]), 3),
            "pipe_friction_factor_multiplier": round(float(self.theta[1]), 3),
            "estimation_variance_annulus": round(float(self.P[0, 0]), 5),
            "estimation_variance_pipe": round(float(self.P[1, 1]), 5),
            "total_calibration_updates": self.updates_count,
        }
