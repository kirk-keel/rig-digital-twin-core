"""Stream processor and real-time execution engine for Rig Digital Twin."""

from __future__ import annotations

from typing import Callable, Iterator, List, Optional, Tuple
from rig_twin.core.models import (
    AlertSeverity,
    AnomalyDetectionResult,
    FluidProperties,
    PhysicsBaseline,
    TelemetryRecord,
    WellGeometry,
)
from rig_twin.ml.kick_detector import KickAndAnomalyDetector
from rig_twin.persistence.repository import TimescaleTwinRepository
from rig_twin.physics.engine import RigPhysicsEngine


class StreamProcessor:
    """Continuous stream processor executing coupled physics-ML evaluation on incoming telemetry."""

    def __init__(
        self,
        geometry: WellGeometry,
        fluid: FluidProperties,
        repository: Optional[TimescaleTwinRepository] = None,
        alert_callback: Optional[Callable[[AnomalyDetectionResult], None]] = None,
        pore_pressure_ppg: float = 9.8,
        fracture_pressure_ppg: float = 14.5,
    ):
        self.geometry = geometry
        self.fluid = fluid
        self.repository = repository
        self.alert_callback = alert_callback

        self.physics_engine = RigPhysicsEngine(geometry=geometry, fluid=fluid)
        self.anomaly_detector = KickAndAnomalyDetector(
            pore_pressure_ppg=pore_pressure_ppg,
            fracture_pressure_ppg=fracture_pressure_ppg,
        )

        if self.repository:
            self.repository.initialize_schema()

    def process_record(
        self, telemetry: TelemetryRecord
    ) -> Tuple[PhysicsBaseline, AnomalyDetectionResult]:
        """Process a single incoming telemetry record through physics and ML anomaly detection."""
        # 1. Deterministic physics calculation
        physics = self.physics_engine.evaluate(telemetry)

        # 2. Coupled ML state estimation and anomaly / kick precursor detection
        anomaly = self.anomaly_detector.evaluate(telemetry, physics)

        # 3. Persistence (if repository configured)
        if self.repository:
            self.repository.log_telemetry_batch([telemetry])
            self.repository.log_physics_batch([physics])
            self.repository.log_anomaly_batch([anomaly])

        # 4. Trigger alert callback if non-normal severity
        if self.alert_callback and anomaly.severity != AlertSeverity.INFO:
            self.alert_callback(anomaly)

        return physics, anomaly

    def process_batch(
        self, records: List[TelemetryRecord]
    ) -> List[Tuple[TelemetryRecord, PhysicsBaseline, AnomalyDetectionResult]]:
        """Process a batch of telemetry records with optimized batch logging."""
        results: List[Tuple[TelemetryRecord, PhysicsBaseline, AnomalyDetectionResult]] = []
        baselines: List[PhysicsBaseline] = []
        anomalies: List[AnomalyDetectionResult] = []

        for record in records:
            phys = self.physics_engine.evaluate(record)
            anom = self.anomaly_detector.evaluate(record, phys)

            baselines.append(phys)
            anomalies.append(anom)
            results.append((record, phys, anom))

            if self.alert_callback and anom.severity != AlertSeverity.INFO:
                self.alert_callback(anom)

        if self.repository and records:
            self.repository.log_telemetry_batch(records)
            self.repository.log_physics_batch(baselines)
            self.repository.log_anomaly_batch(anomalies)

        return results
