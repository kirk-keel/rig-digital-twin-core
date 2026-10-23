# Rig Digital Twin Core - API Reference

The Rig Digital Twin Core provides a high-performance REST and WebSocket API built with FastAPI and Pydantic v2.

---

## 1. General & Health Endpoints

### `GET /`
Returns the Driller Console Web Dashboard HTML page.

### `GET /health`
Returns system liveness, active well connections, and backend operational status.

**Response `200 OK`**:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "active_wells": 1,
  "service": "Rig Digital Twin Core Engine"
}
```

---

## 2. Telemetry & Ingestion Endpoints

### `POST /api/v1/telemetry/ingest`
Ingests a single raw or calibrated `TelemetryRecord` from surface sensors or downhole MWD/PWD tools.

**Request Body**:
```json
{
  "time": "2026-10-23T12:00:00Z",
  "well_id": "DEEPWATER-NAVI-01",
  "measured_depth_ft": 10500.0,
  "true_vertical_depth_ft": 9850.0,
  "flow_rate_in_gpm": 550.0,
  "flow_rate_out_gpm": 551.2,
  "standpipe_pressure_psi": 3250.0,
  "rotary_rpm": 120.0,
  "weight_on_bit_klbf": 25.0,
  "rate_of_penetration_ft_hr": 65.0,
  "surface_torque_ft_lbf": 14200.0,
  "mud_density_in_ppg": 11.8,
  "annular_pressure_pwd_psi": 6120.0,
  "pit_volume_total_bbl": 450.0,
  "active_pit_gain_loss_bbl": 0.2,
  "hook_load_klbf": 285.0
}
```

**Response `200 OK`**:
```json
{
  "status": "accepted",
  "well_id": "DEEPWATER-NAVI-01",
  "timestamp": "2026-10-23T12:00:00Z"
}
```

---

## 3. Physics & Simulation Endpoints

### `POST /api/v1/physics/baseline`
Calculates instantaneous theoretical physics baselines across the discretized wellbore.

**Response `200 OK`**:
```json
{
  "standpipe_pressure_psi": 3242.8,
  "bit_pressure_drop_psi": 1150.4,
  "total_annular_pressure_loss_psi": 385.2,
  "bottom_hole_pressure_psi": 6098.5,
  "equivalent_circulating_density_ppg": 12.18,
  "total_flow_area_sq_in": 0.584,
  "hydraulic_jet_impact_force_lbf": 1024.1
}
```

### `POST /api/v1/physics/safe-tripping-speed`
Optimizes safe pulling (POOH) and running (RIH) velocity limits avoiding swab kicks and formation fracturing.

**Response `200 OK`**:
```json
{
  "max_rih_speed_ft_per_min": 142.5,
  "max_pooh_speed_ft_per_min": 98.2,
  "fracture_pressure_psi": 6480.0,
  "pore_pressure_psi": 5890.0,
  "predicted_ecd_at_max_rih": 12.55,
  "status": "converged"
}
```

### `POST /api/v1/physics/kill-sheet`
Computes complete IADC/API-59 Well Control Kill Sheet.

**Request Body**:
```json
{
  "current_mud_weight_ppg": 11.8,
  "true_vertical_depth_ft": 9850.0,
  "measured_depth_ft": 10500.0,
  "shut_in_drill_pipe_pressure_psi": 450.0,
  "shut_in_casing_pressure_psi": 620.0,
  "pit_gain_bbl": 15.0,
  "slow_circulating_rate_psi": 850.0,
  "leak_off_test_emw_ppg": 14.5,
  "casing_shoe_tvd_ft": 7500.0
}
```

**Response `200 OK`**:
```json
{
  "kill_mud_weight_ppg": 12.68,
  "initial_circulating_pressure_psi": 1300.0,
  "final_circulating_pressure_psi": 913.3,
  "maasp_psi": 1053.0,
  "maximum_allowable_influx_height_ft": 182.4,
  "step_down_schedule": [
    {"strokes": 0, "pressure_psi": 1300.0},
    {"strokes": 200, "pressure_psi": 1222.7},
    {"strokes": 1000, "pressure_psi": 913.3}
  ]
}
```

---

## 4. Autonomous Drilling & Anomaly Detection

### `POST /api/v1/autodriller/advisory`
Evaluates current drilling metrics against MSE, vibrations, and bit wear limits to recommend optimal setpoints.

**Response `200 OK`**:
```json
{
  "recommended_wob_klbf": 28.5,
  "recommended_rpm": 135.0,
  "recommended_flow_rate_gpm": 560.0,
  "predicted_rop_ft_hr": 78.4,
  "expected_mse_psi": 34500.0,
  "vibration_risk_score": 0.12,
  "drilling_efficiency_pct": 88.5
}
```

### `GET /api/v1/anomalies/active`
Retrieves currently triggered anomaly alerts, including kick precursors, swab underbalance, pack-off risk, and washouts.

---

## 5. Streaming WebSocket Protocol

### `WS /ws/telemetry`
High-speed duplex binary or JSON WebSocket connection. Broadcasts streaming telemetry, physics updates, and anomaly flags at up to 10 Hz.

**Sample Message Payload**:
```json
{
  "type": "telemetry_update",
  "well_id": "DEEPWATER-NAVI-01",
  "timestamp": "2026-10-23T12:00:01Z",
  "measured_depth_ft": 10500.5,
  "spp_psi": 3255.0,
  "spp_baseline_psi": 3242.8,
  "ecd_ppg": 12.18,
  "flow_rate_in": 550.0,
  "flow_rate_out": 551.2,
  "anomalies": []
}
```
