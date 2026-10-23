"""FastAPI real-time REST and WebSocket server for Rig Digital Twin Core."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, List, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rig_twin.core.models import (
    AnomalyDetectionResult,
    FluidProperties,
    PhysicsBaseline,
    TelemetryRecord,
    WellGeometry,
)
from rig_twin.demo import build_sample_well
from rig_twin.ingestion.stream_processor import StreamProcessor
from rig_twin.physics.safe_trip_envelope import SafeTripEnvelopeOptimizer
from rig_twin.physics.torque_drag import TorqueDragEngine
from rig_twin.physics.well_control_kill_sheet import (
    WellControlEngine,
    WellControlInput,
    KillSheetResult,
)
from rig_twin.persistence.repository import TimescaleTwinRepository
from rig_twin.streaming.protocols import RigStreamClient


# Global shared twin state
class AppState:
    well: WellGeometry
    fluid: FluidProperties
    repo: TimescaleTwinRepository
    twin: StreamProcessor
    stream_client: RigStreamClient
    connected_websockets: Set[WebSocket] = set()
    latest_telemetry: TelemetryRecord
    latest_physics: PhysicsBaseline
    latest_anomaly: AnomalyDetectionResult
    inject_kick_flag: bool = False


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize twin with North Sea well
    state.well, state.fluid = build_sample_well()
    state.repo = TimescaleTwinRepository("sqlite:///:memory:")
    state.twin = StreamProcessor(
        geometry=state.well,
        fluid=state.fluid,
        repository=state.repo,
        pore_pressure_ppg=10.6,
        fracture_pressure_ppg=14.5,
    )
    state.stream_client = RigStreamClient(well_id=state.well.well_id)

    # Launch background continuous simulation task
    task = asyncio.create_task(background_telemetry_loop())
    yield
    # Shutdown
    state.stream_client.stop()
    task.cancel()


app = FastAPI(
    title="Rig Digital Twin Core API",
    description="Real-time petroleum engineering physics coupled with ML residual state estimation",
    version="0.2.0",
    lifespan=lifespan,
)


async def background_telemetry_loop():
    """Background task streaming real-time simulated telemetry at 1Hz to all connected clients."""
    stream_gen = state.stream_client.generate_simulated_stream(
        base_depth_ft=11450.0,
        flow_rate_gpm=520.0,
        sample_interval_sec=1.0,
        inject_kick_at_step=None,
    )
    kick_steps = 0

    async for record in stream_gen:
        # Check if manual kick injection was triggered
        if state.inject_kick_flag:
            kick_steps += 1
            record.flow_rate_out_gpm += min(kick_steps * 3.5, 30.0)
            record.pit_rate_of_change_bbl_hr += min(kick_steps * 1.5, 10.0)
            record.pit_volume_total_bbl += (record.pit_rate_of_change_bbl_hr / 3600.0)
            record.standpipe_pressure_psi -= min(kick_steps * 2.0, 25.0)

        # Process through physics + ML state estimator
        phys, anom = state.twin.process_record(record)
        state.latest_telemetry = record
        state.latest_physics = phys
        state.latest_anomaly = anom

        # Broadcast to active WebSockets
        if state.connected_websockets:
            payload = json.dumps({
                "type": "telemetry_step",
                "telemetry": record.model_dump(mode="json"),
                "physics": phys.model_dump(mode="json"),
                "anomaly": anom.model_dump(mode="json"),
            })
            dead_ws = set()
            for ws in list(state.connected_websockets):
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead_ws.add(ws)
            state.connected_websockets.difference_update(dead_ws)


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the interactive Driller Console Web Dashboard."""
    static_file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_file):
        with open(static_file, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Rig Digital Twin Core API running</h1>")


@app.get("/health")
async def health_check():
    """System health and uptime check."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "well_id": state.well.well_id,
        "mud_weight_ppg": state.fluid.density_ppg,
        "active_clients": len(state.connected_websockets),
    }


@app.get("/api/well")
async def get_well_configuration():
    """Return active wellbore geometry and fluid rheological properties."""
    return {
        "well": state.well.model_dump(mode="json"),
        "fluid": state.fluid.model_dump(mode="json"),
    }


@app.post("/api/telemetry/ingest")
async def ingest_telemetry_point(record: TelemetryRecord):
    """Ingest a single telemetry point, run physics & ML checks, return prediction delta."""
    phys, anom = state.twin.process_record(record)
    return {
        "telemetry": record.model_dump(mode="json"),
        "physics": phys.model_dump(mode="json"),
        "anomaly": anom.model_dump(mode="json"),
    }


@app.get("/api/safe-trip-envelope")
async def get_safe_tripping_envelope():
    """Return depth-indexed maximum safe pulling (POOH) and running (RIH) tripping speeds."""
    optimizer = SafeTripEnvelopeOptimizer(geometry=state.well, fluid=state.fluid)
    profile = optimizer.generate_safe_trip_profile(max_depth_ft=12000.0, step_ft=1000.0)
    return {"envelope": profile}


@app.post("/api/well-control/kill-sheet")
async def calculate_kill_sheet(inputs: WellControlInput):
    """Compute automated IADC/API-59 Well Control Kill Sheet and circulation pressure schedules."""
    engine = WellControlEngine(inputs)
    result = engine.generate_kill_sheet()
    return result.model_dump(mode="json")


@app.get("/api/torque-drag/broomstick")
async def get_broomstick_curves():
    """Compute 3D Soft-string Johancsik hook load broomstick envelopes."""
    td_engine = TorqueDragEngine(geometry=state.well, fluid=state.fluid)
    curves = td_engine.generate_broomstick_envelope(max_depth_ft=12000.0, step_ft=1000.0)
    return {"broomstick_curves": curves}


@app.post("/api/simulate/kick")
async def trigger_simulated_kick():
    """Trigger an incipient gas influx kick in the real-time simulation feed."""
    state.inject_kick_flag = True
    return {"status": "kick_influx_injected", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.websocket("/ws/stream")
async def websocket_telemetry_stream(websocket: WebSocket):
    """WebSocket endpoint broadcasting real-time telemetry, physics, and ML residuals at 1Hz."""
    await websocket.accept()
    state.connected_websockets.add(websocket)
    try:
        while True:
            # Keep connection open and receive optional client messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        state.connected_websockets.discard(websocket)
    except Exception:
        state.connected_websockets.discard(websocket)
