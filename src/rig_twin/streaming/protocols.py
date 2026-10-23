"""Edge and streaming protocols (ETP, WebSockets, MQTT-ready telemetry ingestion)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from typing import AsyncIterator, Callable, Dict, List, Optional
from rig_twin.core.models import TelemetryRecord
from rig_twin.ingestion.witsml_parser import WitsmlParser


class RigStreamClient:
    """Manages high-throughput real-time telemetry streaming from rig site or edge devices."""

    def __init__(self, well_id: str = "OFFSHORE-01"):
        self.well_id = well_id
        self.is_streaming = False

    async def generate_simulated_stream(
        self,
        base_depth_ft: float = 11450.0,
        flow_rate_gpm: float = 520.0,
        sample_interval_sec: float = 1.0,
        inject_kick_at_step: Optional[int] = 15,
    ) -> AsyncIterator[TelemetryRecord]:
        """Async generator producing realistic 1Hz streaming rig telemetry with optional kick injection."""
        self.is_streaming = True
        step = 0
        depth = base_depth_ft
        pit_vol = 500.0

        while self.is_streaming:
            step += 1
            now = datetime.now(timezone.utc)
            depth += 0.05  # ~180 ft/hr ROP

            delta_flow = 0.0
            pit_roc = 0.0
            spp_val = 4085.0

            # Inject kick precursor if step threshold reached
            if inject_kick_at_step and step >= inject_kick_at_step:
                k_step = step - inject_kick_at_step + 1
                delta_flow = min(k_step * 3.5, 35.0)
                pit_roc = min(k_step * 1.5, 12.0)
                pit_vol += (pit_roc / 3600.0)
                spp_val -= min(k_step * 2.0, 30.0)

            rec = TelemetryRecord(
                timestamp=now,
                well_id=self.well_id,
                measured_depth_ft=round(depth, 2),
                true_vertical_depth_ft=round(depth, 2),
                bit_depth_ft=round(depth, 2),
                hole_depth_ft=round(depth, 2),
                flow_rate_in_gpm=flow_rate_gpm,
                flow_rate_out_gpm=round(flow_rate_gpm + delta_flow, 1),
                standpipe_pressure_psi=round(spp_val, 1),
                hook_load_klbf=245.0,
                surface_rpm=120.0,
                surface_torque_ft_lbf=8400.0,
                mud_weight_in_ppg=11.2,
                mud_weight_out_ppg=11.2 if delta_flow < 10.0 else 10.9,
                pit_volume_total_bbl=round(pit_vol, 2),
                pit_rate_of_change_bbl_hr=round(pit_roc, 2),
            )

            yield rec
            await asyncio.sleep(sample_interval_sec)

    def stop(self) -> None:
        """Stop simulated streaming."""
        self.is_streaming = False
