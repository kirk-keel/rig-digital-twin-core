"""End-to-end integration test of the Rig Digital Twin Core."""

from datetime import datetime, timezone
import pytest
from rig_twin.demo import build_sample_well
from rig_twin.core.models import TelemetryRecord
from rig_twin.ingestion.stream_processor import StreamProcessor
from rig_twin.persistence.repository import TimescaleTwinRepository


def test_end_to_end_twin_pipeline():
    well, fluid = build_sample_well()
    repo = TimescaleTwinRepository("sqlite:///:memory:")

    alerts = []
    processor = StreamProcessor(
        geometry=well,
        fluid=fluid,
        repository=repo,
        alert_callback=lambda a: alerts.append(a),
    )

    records = [
        TelemetryRecord(
            timestamp=datetime.now(timezone.utc),
            well_id=well.well_id,
            measured_depth_ft=11400.0,
            true_vertical_depth_ft=11400.0,
            bit_depth_ft=11400.0,
            hole_depth_ft=11400.0,
            flow_rate_in_gpm=500.0,
            flow_rate_out_gpm=500.0,
            standpipe_pressure_psi=3800.0,
        ),
        TelemetryRecord(
            timestamp=datetime.now(timezone.utc),
            well_id=well.well_id,
            measured_depth_ft=11401.0,
            true_vertical_depth_ft=11401.0,
            bit_depth_ft=11401.0,
            hole_depth_ft=11401.0,
            flow_rate_in_gpm=500.0,
            flow_rate_out_gpm=535.0,  # Influx kick surge
            standpipe_pressure_psi=3780.0,
            pit_rate_of_change_bbl_hr=8.0,
        ),
    ]

    results = processor.process_batch(records)
    assert len(results) == 2
    assert results[0][1].total_predicted_spp_psi > 3000.0
    assert results[0][1].dynamic_ecd_ppg > fluid.density_ppg

    # Check persistence
    logged_telemetry = repo.get_recent_telemetry(well.well_id, limit=10)
    assert len(logged_telemetry) == 2
