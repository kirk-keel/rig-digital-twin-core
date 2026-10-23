"""Multi-Rig and Multi-Well Fleet Orchestrator.

Coordinates concurrent real-time digital twins across an operating fleet,
aggregates basin-wide anomaly alerts, and shares calibrated friction priors.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from rig_twin.core.models import (
    AnomalyDetectionResult,
    FluidProperties,
    PhysicsBaseline,
    TelemetryRecord,
    WellGeometry,
)
from rig_twin.ingestion.stream_processor import StreamProcessor
from rig_twin.persistence.repository import TimescaleTwinRepository


class WellFleetSummary(BaseModel):
    """Real-time executive health summary of a monitored well in the fleet."""
    well_id: str
    last_updated: datetime
    measured_depth_ft: float
    bit_depth_ft: float
    current_mud_weight_ppg: float
    dynamic_ecd_ppg: float
    standpipe_pressure_psi: float
    spp_residual_psi: float
    flow_residual_gpm: float
    latest_status: str
    latest_severity: str
    total_active_alerts: int


class FleetManager:
    """Orchestrates multiple concurrent rig digital twins across an exploration basin."""

    def __init__(self, repository: Optional[TimescaleTwinRepository] = None):
        self.repository = repository
        self.twins: Dict[str, StreamProcessor] = {}
        self.latest_telemetry: Dict[str, TelemetryRecord] = {}
        self.latest_physics: Dict[str, PhysicsBaseline] = {}
        self.latest_anomalies: Dict[str, AnomalyDetectionResult] = {}
        self.active_alert_counts: Dict[str, int] = {}

    def register_well(
        self,
        geometry: WellGeometry,
        fluid: FluidProperties,
        pore_pressure_ppg: float = 10.6,
        fracture_pressure_ppg: float = 14.5,
    ) -> StreamProcessor:
        """Register and initialize a digital twin instance for a new well in the fleet."""
        twin = StreamProcessor(
            geometry=geometry,
            fluid=fluid,
            repository=self.repository,
            pore_pressure_ppg=pore_pressure_ppg,
            fracture_pressure_ppg=fracture_pressure_ppg,
        )
        self.twins[geometry.well_id] = twin
        self.active_alert_counts[geometry.well_id] = 0
        return twin

    def process_telemetry(
        self, telemetry: TelemetryRecord
    ) -> Tuple[PhysicsBaseline, AnomalyDetectionResult]:
        """Route incoming telemetry to the corresponding well digital twin."""
        well_id = telemetry.well_id
        if well_id not in self.twins:
            # Fallback auto-registration with generic offshore profile
            from rig_twin.demo import build_sample_well
            w, f = build_sample_well()
            w.well_id = well_id
            self.register_well(w, f)

        twin = self.twins[well_id]
        phys, anom = twin.process_record(telemetry)

        self.latest_telemetry[well_id] = telemetry
        self.latest_physics[well_id] = phys
        self.latest_anomalies[well_id] = anom

        if anom.severity.value in ("WARNING", "CRITICAL"):
            self.active_alert_counts[well_id] = self.active_alert_counts.get(well_id, 0) + 1

        return phys, anom

    def get_fleet_summary(self) -> List[WellFleetSummary]:
        """Generate high-level fleet-wide monitoring status across all active rigs."""
        summaries: List[WellFleetSummary] = []
        for well_id, twin in self.twins.items():
            t = self.latest_telemetry.get(well_id)
            p = self.latest_physics.get(well_id)
            a = self.latest_anomalies.get(well_id)

            if not t or not p or not a:
                continue

            summaries.append(WellFleetSummary(
                well_id=well_id,
                last_updated=t.timestamp,
                measured_depth_ft=t.measured_depth_ft,
                bit_depth_ft=t.bit_depth_ft,
                current_mud_weight_ppg=t.mud_weight_in_ppg,
                dynamic_ecd_ppg=p.dynamic_ecd_ppg,
                standpipe_pressure_psi=t.standpipe_pressure_psi,
                spp_residual_psi=a.spp_residual_psi,
                flow_residual_gpm=a.flow_residual_gpm,
                latest_status=a.classification.value,
                latest_severity=a.severity.value,
                total_active_alerts=self.active_alert_counts.get(well_id, 0),
            ))

        return summaries
