"""TimescaleDB repository layer for batch time-series persistence and querying."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import create_engine, desc, select, text
from sqlalchemy.orm import Session, sessionmaker

from rig_twin.core.models import (
    AnomalyDetectionResult,
    PhysicsBaseline,
    TelemetryRecord,
)
from rig_twin.persistence.schema import (
    AnomalyEventORM,
    Base,
    PhysicsBaselineORM,
    TelemetryRecordORM,
)


class TimescaleTwinRepository:
    """Repository managing TimescaleDB connection, batch insertion, and historical queries."""

    def __init__(self, connection_url: str = "sqlite:///:memory:"):
        self.connection_url = connection_url
        self.engine = create_engine(connection_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.is_timescaledb = "timescaledb" in connection_url or "postgresql" in connection_url

    def initialize_schema(self) -> None:
        """Create tables and initialize TimescaleDB hypertables if on PostgreSQL/TimescaleDB."""
        Base.metadata.create_all(bind=self.engine)

        if self.is_timescaledb:
            with self.engine.connect() as conn:
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
                    conn.execute(text(
                        "SELECT create_hypertable('telemetry_records', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');"
                    ))
                    conn.execute(text(
                        "SELECT create_hypertable('physics_baselines', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');"
                    ))
                    conn.execute(text(
                        "SELECT create_hypertable('anomaly_events', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');"
                    ))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    # Non-fatal if extension already initialized or testing mock
                    pass

    def log_telemetry_batch(self, records: List[TelemetryRecord]) -> None:
        """Persist a batch of raw telemetry records."""
        if not records:
            return

        orms = [
            TelemetryRecordORM(
                time=r.timestamp,
                well_id=r.well_id,
                measured_depth_ft=r.measured_depth_ft,
                true_vertical_depth_ft=r.true_vertical_depth_ft,
                bit_depth_ft=r.bit_depth_ft,
                hole_depth_ft=r.hole_depth_ft,
                string_velocity_ft_min=r.string_velocity_ft_min,
                flow_rate_in_gpm=r.flow_rate_in_gpm,
                flow_rate_out_gpm=r.flow_rate_out_gpm,
                standpipe_pressure_psi=r.standpipe_pressure_psi,
                downhole_annular_pressure_psi=r.downhole_annular_pressure_psi,
                downhole_ecd_ppg=r.downhole_ecd_ppg,
                hook_load_klbf=r.hook_load_klbf,
                surface_rpm=r.surface_rpm,
                surface_torque_ft_lbf=r.surface_torque_ft_lbf,
                mud_weight_in_ppg=r.mud_weight_in_ppg,
                mud_weight_out_ppg=r.mud_weight_out_ppg,
                pit_volume_total_bbl=r.pit_volume_total_bbl,
                pit_rate_of_change_bbl_hr=r.pit_rate_of_change_bbl_hr,
            )
            for r in records
        ]

        with self.SessionLocal() as session:
            session.bulk_save_objects(orms)
            session.commit()

    def log_physics_batch(self, baselines: List[PhysicsBaseline]) -> None:
        """Persist a batch of deterministic physics baselines."""
        if not baselines:
            return

        orms = [
            PhysicsBaselineORM(
                time=b.timestamp,
                well_id=b.well_id,
                measured_depth_ft=b.measured_depth_ft,
                hydrostatic_pressure_psi=b.hydrostatic_pressure_psi,
                annular_pressure_loss_psi=b.annular_pressure_loss_psi,
                pipe_internal_pressure_loss_psi=b.pipe_internal_pressure_loss_psi,
                bit_pressure_loss_psi=b.bit_pressure_loss_psi,
                total_predicted_spp_psi=b.total_predicted_spp_psi,
                static_ecd_ppg=b.static_ecd_ppg,
                dynamic_ecd_ppg=b.dynamic_ecd_ppg,
                surge_pressure_loss_psi=b.surge_pressure_loss_psi,
                swab_pressure_loss_psi=b.swab_pressure_loss_psi,
                effective_ecd_surge_ppg=b.effective_ecd_surge_ppg,
                effective_ecd_swab_ppg=b.effective_ecd_swab_ppg,
                annulus_flow_regime=b.annulus_flow_regime,
                pipe_flow_regime=b.pipe_flow_regime,
                bit_jet_impact_force_lbf=b.bit_jet_impact_force_lbf,
                bit_hydraulic_horsepower_hhp=b.bit_hydraulic_horsepower_hhp,
            )
            for b in baselines
        ]

        with self.SessionLocal() as session:
            session.bulk_save_objects(orms)
            session.commit()

    def log_anomaly_batch(self, anomalies: List[AnomalyDetectionResult]) -> None:
        """Persist a batch of ML state estimation anomaly events."""
        if not anomalies:
            return

        orms = [
            AnomalyEventORM(
                time=a.timestamp,
                well_id=a.well_id,
                measured_depth_ft=a.measured_depth_ft,
                classification=a.classification.value,
                severity=a.severity.value,
                anomaly_score=a.anomaly_score,
                spp_residual_psi=a.spp_residual_psi,
                flow_residual_gpm=a.flow_residual_gpm,
                ecd_residual_ppg=a.ecd_residual_ppg,
                pit_residual_bbl_min=a.pit_residual_bbl_min,
                detection_rule=a.detection_rule,
                diagnostic_message=a.diagnostic_message,
                recommended_action=a.recommended_action,
            )
            for a in anomalies
        ]

        with self.SessionLocal() as session:
            session.bulk_save_objects(orms)
            session.commit()

    def get_recent_telemetry(self, well_id: str, limit: int = 100) -> List[TelemetryRecordORM]:
        """Query most recent telemetry records for a well."""
        with self.SessionLocal() as session:
            stmt = (
                select(TelemetryRecordORM)
                .where(TelemetryRecordORM.well_id == well_id)
                .order_by(desc(TelemetryRecordORM.time))
                .limit(limit)
            )
            return list(session.scalars(stmt).all())

    def get_recent_anomalies(
        self, well_id: str, severity: Optional[str] = None, limit: int = 50
    ) -> List[AnomalyEventORM]:
        """Query recent anomaly alerts filtered by well and severity."""
        with self.SessionLocal() as session:
            stmt = select(AnomalyEventORM).where(AnomalyEventORM.well_id == well_id)
            if severity:
                stmt = stmt.where(AnomalyEventORM.severity == severity)
            stmt = stmt.order_by(desc(AnomalyEventORM.time)).limit(limit)
            return list(session.scalars(stmt).all())
