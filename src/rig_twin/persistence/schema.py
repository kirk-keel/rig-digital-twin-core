"""SQLAlchemy schema models for TimescaleDB time-series storage."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TelemetryRecordORM(Base):
    """Raw WITSML streaming telemetry hypertable model."""
    __tablename__ = "telemetry_records"

    time = Column(DateTime(timezone=True), nullable=False)
    well_id = Column(String(64), nullable=False)
    measured_depth_ft = Column(Float, nullable=False)
    true_vertical_depth_ft = Column(Float, nullable=False)
    bit_depth_ft = Column(Float, nullable=False)
    hole_depth_ft = Column(Float, nullable=False)

    string_velocity_ft_min = Column(Float, nullable=False, default=0.0)
    flow_rate_in_gpm = Column(Float, nullable=False, default=0.0)
    flow_rate_out_gpm = Column(Float, nullable=False, default=0.0)
    standpipe_pressure_psi = Column(Float, nullable=False, default=0.0)
    downhole_annular_pressure_psi = Column(Float, nullable=True)
    downhole_ecd_ppg = Column(Float, nullable=True)

    hook_load_klbf = Column(Float, nullable=False, default=0.0)
    surface_rpm = Column(Float, nullable=False, default=0.0)
    surface_torque_ft_lbf = Column(Float, nullable=False, default=0.0)

    mud_weight_in_ppg = Column(Float, nullable=False, default=10.0)
    mud_weight_out_ppg = Column(Float, nullable=False, default=10.0)
    pit_volume_total_bbl = Column(Float, nullable=False, default=500.0)
    pit_rate_of_change_bbl_hr = Column(Float, nullable=False, default=0.0)

    __table_args__ = (
        PrimaryKeyConstraint("time", "well_id", "measured_depth_ft"),
        Index("idx_telemetry_time_well", "well_id", "time"),
    )


class PhysicsBaselineORM(Base):
    """Deterministic petroleum physics calculations hypertable model."""
    __tablename__ = "physics_baselines"

    time = Column(DateTime(timezone=True), nullable=False)
    well_id = Column(String(64), nullable=False)
    measured_depth_ft = Column(Float, nullable=False)

    hydrostatic_pressure_psi = Column(Float, nullable=False)
    annular_pressure_loss_psi = Column(Float, nullable=False)
    pipe_internal_pressure_loss_psi = Column(Float, nullable=False)
    bit_pressure_loss_psi = Column(Float, nullable=False)
    total_predicted_spp_psi = Column(Float, nullable=False)

    static_ecd_ppg = Column(Float, nullable=False)
    dynamic_ecd_ppg = Column(Float, nullable=False)
    surge_pressure_loss_psi = Column(Float, nullable=False, default=0.0)
    swab_pressure_loss_psi = Column(Float, nullable=False, default=0.0)
    effective_ecd_surge_ppg = Column(Float, nullable=False, default=0.0)
    effective_ecd_swab_ppg = Column(Float, nullable=False, default=0.0)

    annulus_flow_regime = Column(String(32), nullable=False)
    pipe_flow_regime = Column(String(32), nullable=False)
    bit_jet_impact_force_lbf = Column(Float, nullable=False, default=0.0)
    bit_hydraulic_horsepower_hhp = Column(Float, nullable=False, default=0.0)

    __table_args__ = (
        PrimaryKeyConstraint("time", "well_id", "measured_depth_ft"),
        Index("idx_physics_time_well", "well_id", "time"),
    )


class AnomalyEventORM(Base):
    """ML state estimation residuals and anomaly flags hypertable model."""
    __tablename__ = "anomaly_events"

    time = Column(DateTime(timezone=True), nullable=False)
    well_id = Column(String(64), nullable=False)
    measured_depth_ft = Column(Float, nullable=False)

    classification = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False)
    anomaly_score = Column(Float, nullable=False)

    spp_residual_psi = Column(Float, nullable=False)
    flow_residual_gpm = Column(Float, nullable=False)
    ecd_residual_ppg = Column(Float, nullable=True)
    pit_residual_bbl_min = Column(Float, nullable=False, default=0.0)

    detection_rule = Column(String(128), nullable=False)
    diagnostic_message = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("time", "well_id", "measured_depth_ft"),
        Index("idx_anomalies_time_well", "well_id", "time"),
        Index("idx_anomalies_severity_time", "severity", "time"),
    )
