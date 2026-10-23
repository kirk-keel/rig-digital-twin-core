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
from rig_twin.core.fleet import FleetManager
from rig_twin.physics.casing_wear import CasingWearAndFatigueEngine
from rig_twin.physics.safe_trip_envelope import SafeTripEnvelopeOptimizer
from rig_twin.physics.torque_drag import TorqueDragEngine
from rig_twin.physics.transient_hydraulics import TransientHydraulicsEngine
from rig_twin.physics.vibrations import DrillstringDynamicsEngine
from rig_twin.physics.well_control_kill_sheet import (
    WellControlEngine,
    WellControlInput,
    KillSheetResult,
)
from rig_twin.physics.what_if_sandbox import WhatIfSandbox
from rig_twin.persistence.repository import TimescaleTwinRepository
from rig_twin.streaming.protocols import RigStreamClient


# Global shared twin state
class AppState:
    well: WellGeometry
    fluid: FluidProperties
    repo: TimescaleTwinRepository
    twin: StreamProcessor
    fleet: FleetManager
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
    state.fleet = FleetManager(repository=state.repo)
    state.fleet.register_well(state.well, state.fluid, pore_pressure_ppg=10.6, fracture_pressure_ppg=14.5)
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

        # Update fleet cache
        state.fleet.latest_telemetry[record.well_id] = record
        state.fleet.latest_physics[record.well_id] = phys
        state.fleet.latest_anomalies[record.well_id] = anom
        if anom.severity.value in ("WARNING", "CRITICAL"):
            state.fleet.active_alert_counts[record.well_id] = state.fleet.active_alert_counts.get(record.well_id, 0) + 1

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


@app.get("/api/vibrations/bha")
async def get_bha_vibration_evaluation():
    """Evaluate 3-axis BHA resonance, forward/backward whirl, and safe RPM windows."""
    engine = DrillstringDynamicsEngine(drillstring_length_ft=state.latest_telemetry.measured_depth_ft if hasattr(state, 'latest_telemetry') else 11450.0)
    result = engine.evaluate_safe_operating_rpm_bands()
    return result.model_dump(mode="json")


@app.get("/api/transient/waterhammer")
async def get_transient_waterhammer(flow_gpm: float = 520.0, closure_sec: float = 0.5):
    """Simulate Joukowsky waterhammer pressure surge and casing burst safety."""
    engine = TransientHydraulicsEngine(fluid=state.fluid)
    result = engine.simulate_valve_closure_surge(flow_rate_gpm=flow_gpm, valve_closure_time_sec=closure_sec)
    return result.model_dump(mode="json")


@app.get("/api/casing/wear")
async def get_casing_wear(depth_ft: float = 8500.0, hours: float = 72.0, rpm: float = 120.0):
    """Calculate White & Dawson casing wear and Palmgren-Miner cyclic drillpipe fatigue."""
    engine = CasingWearAndFatigueEngine()
    wear = engine.calculate_casing_wear(depth_ft=depth_ft, contact_force_lbf=1200.0, dogleg_deg_100ft=2.5, rotating_hours=hours, rpm=rpm)
    fatigue = engine.calculate_drillpipe_fatigue(depth_ft=depth_ft, dogleg_deg_100ft=2.5, rotating_hours=hours, rpm=rpm)
    return {
        "casing_wear": wear.model_dump(mode="json"),
        "drillpipe_fatigue": fatigue.model_dump(mode="json"),
    }


@app.get("/api/fleet/summary")
async def get_fleet_summary():
    """Return real-time operational status across the entire rig fleet."""
    return {"fleet": [s.model_dump(mode="json") for s in state.fleet.get_fleet_summary()]}


@app.post("/api/what-if/simulate")
async def simulate_what_if_scenario(
    scenario_type: str = "FLOW_STEP",
    target_value: float = 580.0,
):
    """Run an automated what-if forward simulation (FLOW_STEP, MUD_WEIGHT, TRIPPING_SPEED)."""
    tel = state.latest_telemetry if hasattr(state, 'latest_telemetry') else TelemetryRecord(
        timestamp=datetime.now(timezone.utc),
        well_id=state.well.well_id,
        measured_depth_ft=11450.0,
        true_vertical_depth_ft=11450.0,
        bit_depth_ft=11450.0,
        hole_depth_ft=11450.0,
        flow_rate_in_gpm=520.0,
        flow_rate_out_gpm=520.0,
        standpipe_pressure_psi=4085.0,
    )
    sandbox = WhatIfSandbox(geometry=state.well, fluid=state.fluid, current_telemetry=tel)

    if scenario_type == "FLOW_STEP":
        res = sandbox.simulate_flow_rate_step(target_flow_gpm=target_value)
    elif scenario_type == "MUD_WEIGHT":
        res = sandbox.simulate_mud_weight_change(target_mud_weight_ppg=target_value)
    elif scenario_type == "TRIPPING_SPEED":
        res = sandbox.simulate_tripping_speed(target_velocity_ft_min=target_value)
    else:
        res = sandbox.simulate_flow_rate_step(target_flow_gpm=target_value)

    return res.model_dump(mode="json")


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
