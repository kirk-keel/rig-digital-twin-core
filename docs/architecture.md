# Rig Digital Twin Core - Architecture Overview

`rig-digital-twin-core` is an industrial-grade, real-time wellbore simulation engine designed for autonomous and advisory drilling operations. The architecture is built around decoupled layers separating data ingestion, deterministic petroleum physics, machine learning state estimators, operational advisory controllers, and high-performance time-series persistence.

---

## 1. System Architecture Diagram

```mermaid
flowchart TD
    subgraph Rigsite_Telemetry["1. Rigsite Telemetry Ingestion"]
        WITS0["WITS Level 0 TCP Feed (9090)"]
        WITSML["WITSML 1.3.1 / 1.4.1 (XML / JSON)"]
        STREAM["StreamProcessor / Parser Pipeline"]
        WITS0 --> STREAM
        WITSML --> STREAM
    end

    subgraph Deterministic_Physics["2. Discretized Physics Engine (API / IADC)"]
        GEOM["Discretized Wellbore Geometry (100 ft cells)"]
        RHEO["Herschel-Bulkley Non-Newtonian Rheology"]
        HYDR["Annular & Pipe Hydraulics (SPP, ECD, TFA)"]
        TD3D["Johancsik 3D Torque & Drag / Buckling"]
        DYN["BHA Whirl & Campbell Resonance Dynamics"]
        WH["Joukowsky Waterhammer Transient Surge"]
        GEOP["Eaton Pore Pressure & Matthews-Kelly Frac"]
        SURG["Burkhardt / Lubinski Surge & Swab"]
        
        GEOM --> RHEO --> HYDR
        GEOM --> TD3D
        GEOM --> DYN
        HYDR --> WH
        GEOM --> GEOP
        RHEO --> SURG
    end

    subgraph ML_State_Estimation["3. State Estimation & ML Anomaly Detection"]
        RESID["Physics Residual Calculation: r(t) = y_obs(t) - y_phys(t)"]
        KALMAN["Kalman Residual Filter (Denoising)"]
        CUSUM["Two-Sided Page-Hinkley CUSUM Detector"]
        BAYES["Online Bayesian Parameter Calibrator"]
        ALERT["Multi-Precursor Early Warning Classifier"]
        
        RESID --> KALMAN --> CUSUM --> ALERT
        RESID --> BAYES --> RHEO
    end

    subgraph Operational_Advisory["4. Operational Advisory & Presentation"]
        KILL["IADC/API-59 Well Control Kill Sheet"]
        AUTOD["AutoDriller Closed-Loop Advisory (WOB, RPM, Q)"]
        SAFE_TRIP["Safe Tripping Speed Optimizer (Brent's Method)"]
        REPORT["Post-Mortem Incident Exporter (JSON/Markdown)"]
        UI["Real-Time HTML5/Canvas Driller Console (8000)"]
        REST["FastAPI REST & WebSocket Server"]
        
        ALERT --> KILL
        ALERT --> AUTOD
        HYDR --> SAFE_TRIP
        ALERT --> REPORT
        REST --> UI
    end

    subgraph Persistence["5. Persistence & Hypertables"]
        PG["PostgreSQL 16 + TimescaleDB"]
        HYPER1["raw_telemetry (1-day chunks, compressed)"]
        HYPER2["anomaly_events (indexed incidents)"]
        ROLLUP["Continuous Aggregate Rollups (1-min buckets)"]
        PG --> HYPER1
        PG --> HYPER2
        HYPER1 --> ROLLUP
    end

    STREAM --> RESID
    STREAM --> Deterministic_Physics
    Deterministic_Physics --> RESID
    ALERT --> REST
    AUTOD --> REST
    STREAM --> PG
    ALERT --> PG
```

---

## 2. Decoupled Architectural Layers

### Layer 1: Ingestion & Telemetry Normalization (`rig_twin.ingestion`)
- **`wits0_parser.py`**: High-throughput asynchronous TCP server decoding WITS Level 0 packets (Record Type 01, general drilling) with bi-directional encoder support.
- **`witsml_parser.py`**: Robust parser handling both hierarchical XML schemas (WITSML 1.3.1, 1.4.1) and JSON envelopes, standardizing telemetry into unified `TelemetryRecord` models.
- **`stream_processor.py`**: Continuous async stream orchestrator linking incoming rig sensors to the physics engine, statistical estimators, and persistence queue.

### Layer 2: Deterministic Petroleum Physics Engine (`rig_twin.physics`)
Discretizes the entire wellbore from surface to Total Depth (TD) into spatial intervals (typically $\Delta L = 100\text{ ft}$) and executes deterministic formulations:
- **`rheology.py`**: Herschel-Bulkley ($n$, $K$, $\tau_0$), Bingham Plastic, and Power-Law models with API RP 13D golden-section search regression.
- **`hydraulics.py`**: Discretized drillstring bore, annular frictional pressure losses, bit nozzle jet impact velocity, and Equivalent Circulating Density ($ECD$).
- **`torque_drag.py`**: 3D Johancsik soft-string tension/torque integration, normal contact loads, Dawson-Paslay sinusoidal buckling, and Lubinski helical buckling limits.
- **`vibrations.py`**: 3-axis BHA drillstring dynamics, torsional stick-slip severity, lateral/axial whirl frequencies, and Campbell diagram critical RPM avoidance windows.
- **`transient_hydraulics.py`**: Joukowsky acoustic wave transient surge calculation during sudden valve closures or pump trips.
- **`geopressure.py`**: Dynamic Eaton pore pressure prediction from corrected $d_{xc}$ exponents and Matthews-Kelly fracture gradient envelopes.
- **`well_control_kill_sheet.py`**: Automated IADC / API-59 Kill Sheet generator computing Kill Mud Weight ($KMW$), Initial Circulating Pressure ($ICP$), Final Circulating Pressure ($FCP$), MAASP, and step-down schedules.

### Layer 3: Machine Learning & State Estimation (`rig_twin.ml`)
- **`estimator.py`**: Isolates physical sensor residuals $r_t = y_{\text{obs},t} - y_{\text{phys},t}$, denoises through a 1D recursive Kalman filter, and monitors cumulative deviations with two-sided Page-Hinkley CUSUM algorithms.
- **`kick_detector.py`**: Real-time multi-signature classifier distinguishing kick precursors, swab underbalance, pack-offs, and washouts with early severity scoring.
- **`auto_calibrator.py`**: Bayesian online parameter updater tuning downhole friction factors and rheological yield stresses against clean steady-state flow windows.
- **`autodriller.py`**: Closed-loop advisory calculating optimal $[WOB, RPM, Flow Rate]$ setpoints to maximize ROP while staying bounded inside vibration and ECD safety limits.

### Layer 4: Presentation & Multi-Rig Orchestration (`rig_twin.server`, `rig_twin.core`)
- **`api.py`**: High-performance FastAPI server exposing typed REST endpoints and low-latency WebSocket streams for streaming telemetry broadcasts.
- **`static/index.html`**: Zero-dependency dark-mode Driller Console dashboard displaying real-time gauges, rolling strip charts, alarm banners, and 3D wellbore schematic views.
- **`fleet.py`**: Centralized multi-rig orchestrator supervising an entire fleet of drilling rigs simultaneously.
- **`what_if_sandbox.py`**: Safe simulated sandbox enabling drilling engineers to model alternative operational scenarios (e.g. mud weight weighting, tripping speeds) before field execution.

### Layer 5: Time-Series Persistence (`rig_twin.persistence`)
- **`schema.py`**: SQLAlchemy ORM definitions for PostgreSQL/TimescaleDB.
- **`repository.py`**: High-speed batch writer inserting time-series telemetry records into hypertable chunks partitioned by timestamp and wellbore ID.
