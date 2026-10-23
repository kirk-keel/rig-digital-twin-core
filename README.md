# rig-digital-twin-core

[![CI Tests](https://img.shields.io/badge/tests-38%20passed-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)]()
[![Physics](https://img.shields.io/badge/physics-Herschel--Bulkley%20%7C%20API%20RP%2013D-orange.svg)]()
[![Torque & Drag](https://img.shields.io/badge/mechanics-3D%20Johancsik%20Soft--String-yellow.svg)]()
[![Database](https://img.shields.io/badge/timeseries-TimescaleDB-blueviolet.svg)]()
[![Dashboard](https://img.shields.io/badge/console-FastAPI%20%2B%20WebSocket%20UI-success.svg)]()

**rig-digital-twin-core** is a real-time wellbore simulation and predictive digital twin engine for oil and gas drilling operations. It couples high-fidelity, deterministic petroleum engineering physics (wellbore hydraulics, Herschel-Bulkley non-Newtonian rheology, annular pressure losses, bit nozzle jet dynamics, surge/swab tripping kinematics) with adaptive machine learning state estimators.

The system ingests streaming WITSML telemetry, dynamically computes theoretical physics baselines across discretized wellbore intervals, models physical residuals using Kalman filters and CUSUM change-point detectors, and alerts drillers to kick precursors, swab underbalance, incipient pack-offs, and bit washouts **minutes before traditional surface tank indicators register them**.

---

## Architecture Overview

```
                      +---------------------------------------+
                      |       Streaming Telemetry Feed        |
                      |   (WITSML 1.3.1 / 1.4.1 XML / JSON)   |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |       WitsmlParser & Normalizer       |
                      |  (Depth, Flow In/Out, SPP, PWD, RPM)  |
                      +-------------------+-------------------+
                                          |
                   +----------------------+----------------------+
                   |                                             |
                   v                                             v
     +---------------------------+                 +---------------------------+
     |   RigPhysicsEngine (CPE)  |                 |     Telemetry Stream      |
     | - Herschel-Bulkley (API)  |                 |    (Observed Values)      |
     | - Drillstring Frictional  |                 |                           |
     | - Annular Pressure Loss   |                 | - SPP_obs                 |
     | - Bit Nozzle Hydraulics   |                 | - Flow_out, Flow_in       |
     | - Dynamic Surge / Swab    |                 | - PWD Annular ECD         |
     +-------------+-------------+                 +-------------+-------------+
                   |                                             |
                   | Theoretical Baseline (y_phys)               | Real-Time Observation (y_obs)
                   +----------------------+----------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |   Physics-ML Residual Extraction      |
                      |        r_t = y_obs,t - y_phys,t       |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |   Kalman Residual Filter & CUSUM      |
                      | - Steady-state bias tracking (cuttings)|
                      | - High-frequency anomaly deviation    |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |      Kick & Rig Anomaly Detector      |
                      | - Incipient Kick (Delta-Flow Discrep) |
                      | - Swab Underbalance (POOH Risk)       |
                      | - Surge Formation Breakdown (RIH)     |
                      | - Bit Washout vs Incipient Pack-Off   |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |        TimescaleDB Persistence        |
                      | - telemetry_records (hypertable)      |
                      | - physics_baselines (hypertable)      |
                      | - anomaly_events (hypertable)         |
                      | - Continuous Aggregates (1-min rollup)|
                      +---------------------------------------+
```

---

## 1. Deterministic Petroleum Physics Formulation

### 1.1 Non-Newtonian Rheology (API RP 13D / Herschel-Bulkley)
Drilling fluids exhibit non-Newtonian, pseudoplastic, yield-stress behavior. The primary constitutive model implemented is the **Herschel-Bulkley (Yield-Power-Law, YPL)** model:

$$\tau = \tau_0 + K \dot{\gamma}^n$$

- $\tau$: Shear stress ($\text{lbf}/100\,\text{ft}^2$ or $\text{Pa}$)
- $\tau_0$: Yield stress ($\text{lbf}/100\,\text{ft}^2$)
- $K$: Consistency index ($\text{lbf}\cdot\text{s}^n/100\,\text{ft}^2$)
- $n$: Flow behavior index (dimensionless; $n < 1$ represents shear thinning)
- $\dot{\gamma}$: Shear rate ($\text{s}^{-1}$)

The engine also provides fallback support for **Bingham-Plastic** ($\tau = \text{YP} + \text{PV} \cdot \dot{\gamma}$) and **Power-Law** fluids.

#### Wall Shear Rates
- **Inside Circular Drillpipe:**
  $$\dot{\gamma}_{p} = \left(\frac{3n + 1}{4n}\right) \frac{8 v}{d_{id}}$$
- **Inside Wellbore Annulus (Concentric Cylinders / Narrow Slot):**
  $$\dot{\gamma}_{a} = \left(\frac{2n + 1}{3n}\right) \frac{12 v}{d_{h} - d_{p}}$$

#### Generalized Reynolds Number & Friction Factors
$$\text{Re}_g = \frac{928 \cdot \rho \cdot v \cdot d_{id}}{\mu_{eff}} \quad (\text{Pipe}), \qquad \text{Re}_g = \frac{757 \cdot \rho \cdot v \cdot (d_h - d_p)}{\mu_{eff}} \quad (\text{Annulus})$$

Critical Reynolds number transition occurs at $\text{Re}_{crit} = 2100 \sqrt{n}$. Fanning friction factor $f$ is solved as:
- **Laminar Flow ($\text{Re} < \text{Re}_{crit}$):** $f = \frac{16}{\text{Re}}$ (pipe), $f = \frac{24}{\text{Re}}$ (annulus)
- **Turbulent Flow:** Dodge-Metzner correlation for non-Newtonian fluids:
  $$f = \frac{0.0791 \cdot n^{0.67}}{\text{Re}_g^{0.25}}$$

---

### 1.2 Hydraulics, Annular Pressure Loss & ECD

1. **Hydrostatic Pressure:**
   $$P_{\text{hydro}} = 0.052 \cdot \rho_{\text{mud}}\,[\text{ppg}] \cdot \text{TVD}\,[\text{ft}]$$

2. **Frictional Pressure Loss Across Interval $\Delta L$:**
   $$\Delta P_{\text{friction}} = \frac{f \cdot \rho_{\text{mud}} \cdot v^2 \cdot \Delta L}{25.8 \cdot D_{\text{hyd}}}$$

3. **Bit Nozzle Hydraulics:**
   Given Total Flow Area $\text{TFA} = \sum \frac{\pi}{4} \left(\frac{d_n}{32}\right)^2$:
   $$\Delta P_{\text{bit}} = \frac{\rho \cdot Q^2}{10858 \cdot C_d^2 \cdot \text{TFA}^2}$$
   $$v_{\text{jet}} = \frac{Q}{3.117 \cdot \text{TFA}}, \quad \text{HHP} = \frac{\Delta P_{\text{bit}} \cdot Q}{1714}, \quad F_{\text{impact}} = 0.01823 \cdot C_d \cdot Q \sqrt{\rho \cdot \Delta P_{\text{bit}}}$$

4. **Total Standpipe Pressure (SPP):**
   $$\text{SPP}_{\text{pred}} = \Delta P_{\text{surface}} + \Delta P_{\text{drillstring}} + \Delta P_{\text{bit}} + \Delta P_{\text{annular}}$$

5. **Equivalent Circulating Density (ECD):**
   $$\text{ECD} = \rho_{\text{mud}} + \frac{\Delta P_{\text{annular}}}{0.052 \cdot \text{TVD}}$$

---

### 1.3 Dynamic Surge & Swab Kinematics (Tripping Dynamics)

When moving pipe through fluid at velocity $v_p$, viscous drag and displaced volume create dynamic bottomhole pressure fluctuations:
- **Tripping In (RIH, $v_p > 0$):** Dynamic **Surge** pressure ($\Delta P_{\text{surge}}$) increases bottomhole pressure, threatening formation breakdown.
- **Pulling Out (POOH, $v_p < 0$):** Dynamic **Swab** pressure ($\Delta P_{\text{swab}}$) decreases bottomhole pressure, risking kick influx from permeable formations.

#### Burkhardt & Lubinski Formulations
- **Clinging Factor $K_c$:** Fraction of fluid boundary layer adhering to the drillstring:
  $$K_c \approx \left[\frac{1 - (d_p/d_h)^2}{2 \ln(d_h/d_p)} - (d_p/d_h)^2\right] \cdot (0.8 + 0.2 n)$$
- **Effective Fluid Velocity:**
  $$v_{\text{eff}} = |v_p| \left( \frac{d_p^2}{d_h^2 - d_p^2} + K_c \right) \quad (\text{Closed Float Valve})$$
- **Dynamic Effective ECD:**
  $$\text{ECD}_{\text{surge}} = \text{ECD} + \frac{\Delta P_{\text{surge}}}{0.052 \cdot \text{TVD}}, \qquad \text{ECD}_{\text{swab}} = \max\left(\text{ECD}_{\text{static}} - \frac{\Delta P_{\text{swab}}}{0.052 \cdot \text{TVD}}, 0\right)$$

---

## 2. Coupling Deterministic Physics with ML Residuals

### Why Pure Machine Learning Fails on Drilling Rigs
1. **Out-of-Distribution Vulnerability:** Drilling operations transition rapidly between circulation rates, mud weights, casing depths, and string velocities. Pure black-box neural networks or regressors hallucinate unphysical predictions outside trained operational envelopes.
2. **Lack of Conservation Laws:** Black-box ML models do not enforce mass conservation ($Q_{in} = Q_{out}$) or momentum balance.
3. **Sparse Training Data for Catastrophic Events:** Real blowouts and kicks are rare; training a supervised classifier directly on surface data results in poor generalization and high false alarm rates.

### The Physics-Informed Residual Solution
The digital twin establishes the deterministic petroleum physics engine as a **zero-order prior (inductive bias)**:

$$y_{\text{obs}}(t) = f_{\text{physics}}(X(t); \mathbf{\theta}) + \hat{r}_{\text{ML}}(t) + \epsilon(t)$$

1. **Deterministic Baseline $f_{\text{physics}}$:** Computes nominal SPP, annular pressure loss, and ECD from fluid rheology, string geometry, and mud weight.
2. **First-Order Residual $r(t) = y_{\text{obs}}(t) - y_{\text{physics}}(t)$:** Captures systematic wellbore effects:
   - Gradual cuttings bed accumulation.
   - Temperature degradation of mud downhole.
   - Pipe wall roughness variations.
3. **Adaptive State Estimator (Kalman Filter):** Tracks the steady-state bias $\hat{r}_{\text{ML}}(t)$.
4. **Second-Order Deviation $\delta(t) = r(t) - \hat{r}_{\text{ML}}(t)$:** Measures unexpected high-frequency divergence.
5. **CUSUM Change-Point & Anomaly Scoring:** Identifies physical downhole signatures:

| Downhole Phenomenon | $\Delta \text{SPP} = \text{SPP}_{\text{obs}} - \text{SPP}_{\text{phys}}$ | $\Delta Q = Q_{\text{out}} - Q_{\text{in}}$ | Pit Rate of Change | PWD ECD Response |
| :--- | :--- | :--- | :--- | :--- |
| **Incipient Kick (Precursor)** | Slight decrease / steady | **Positive ($> +12\,\text{gpm}$)** | **Rising ($> +2\,\text{bbl/hr}$)** | Decreasing / Underbalance |
| **Swab-Induced Kick Risk** | N/A (pumps off) | Zero / Mud falling | Depleting (lack of fill) | **$\text{ECD}_{\text{swab}} < \text{Pore Pressure}$** |
| **Lost Circulation** | Decreasing | **Negative ($< -12\,\text{gpm}$)** | **Dropping ($< -3\,\text{bbl/hr}$)** | Dropping |
| **Incipient Pack-Off** | **Surging ($> +120\,\text{psi}$)** | Balanced | Steady | Surging |
| **Bit Nozzle Washout** | **Steadily Dropping ($< -90\,\text{psi}$)** | Balanced | Steady | Normal |
| **Sensor Zero Drift** | Constant Static Bias | Balanced | Steady | Normal |

---

## 3. Persistence & TimescaleDB Hypertables

All streaming telemetry, computed physics baselines, and ML prediction deltas are persisted into TimescaleDB hypertables partitioned on `time` with automatic chunking and columnar compression:

- **`telemetry_records`**: Raw streaming WITSML records (indices on `(well_id, time DESC)` and `(well_id, measured_depth_ft DESC)`).
- **`physics_baselines`**: Hydrostatic, annular losses, bit losses, theoretical SPP, dynamic ECD, and surge/swab margins.
- **`anomaly_events`**: Anomaly score, classification label, severity, diagnostic narrative, and recommended actions.
- **`drilling_minute_summary`**: TimescaleDB Continuous Materialized View aggregating minute-by-minute hydraulic rollups.

---

## 4. Enhanced Physics, Optimization & Well Control Modules

### 4.1 Wellbore Thermal & Pressure-Dependent PVT Modeling ($\rho(P, T)$)
Calculates transient temperature profiles inside drillstring and annulus (Hasan & Kabir formulation) and couples real-time density corrections:
$$\rho(P, T) = \rho_0 \left[1 + \frac{P - P_0}{B_m} - \alpha_m (T - T_0)\right]$$
Includes Arrhenius temperature thinning adjustments for effective downhole viscosity.

### 4.2 3D Soft-String Torque & Drag (Johancsik Formulation)
Integrates normal contact forces, buoyant drillstring weight, and 3D wellbore curvature:
- Calculates **Pick-up**, **Slack-off**, and **Rotating Off-Bottom** surface hook loads.
- Evaluates Dawson-Paslay sinusoidal buckling and Chen-Cheatham helical buckling limits.
- Generates complete multi-friction-coefficient ($\mu = 0.15, 0.25, 0.35$) **Broomstick Envelopes** for stuck pipe prevention.

### 4.3 Cuttings Transport & Hole Cleaning Index (HCI)
Evaluates Larsen & Moore cuttings mechanics:
- Computes particle slip velocity ($v_{\text{slip}}$) in non-Newtonian drilling fluids.
- Determines critical transport fluid velocity ($v_{\text{crit}}$) to prevent cuttings bed accumulation.
- Calculates in-situ cuttings concentration and dynamic **Hole Cleaning Index (HCI)**, dynamically feeding friction factor multipliers back into the hydraulics engine.

### 4.4 Two-Phase Gas Influx Migration & Boyle Expansion
Simulates gas slip velocity and real-time bubble expansion using the Zuber-Findlay drift-flux model:
$$v_g = C_0 \cdot v_m + v_d, \qquad V_2 = V_1 \left(\frac{P_1}{P_2}\right) \left(\frac{T_2}{T_1}\right) \left(\frac{Z_2}{Z_1}\right)$$
Predicts time remaining before gas reaches the subsea or surface Blowout Preventer (BOP).

### 4.5 Safe Tripping Speed Envelope Optimizer
Inverts non-linear surge and swab physics via numerical root finding (`scipy.optimize.brentq`):
- Dynamically computes the **Maximum Safe Pulling Speed (POOH)** to keep effective swab ECD strictly above formation pore pressure + safety margin.
- Dynamically computes the **Maximum Safe Running Speed (RIH)** to prevent surging above formation breakdown/fracture gradient.

### 4.6 Automated Well Control Kill Sheet (API RP 59 / IADC Standards)
When shut in on a kick, automatically computes:
- Kill Mud Weight ($\text{KMW}$), Initial Circulating Pressure ($\text{ICP}$), and Final Circulating Pressure ($\text{FCP}$).
- Initial and Kill MAASP (Maximum Allowable Annular Surface Pressure).
- Drillstring and annular pump stroke requirements.
- Generates complete stroke-by-stroke pressure step-down schedules for the **Wait & Weight Method** and **Driller's Method**.

### 4.7 Mechanical Specific Energy (MSE) & Bit Dysfunction Tracker
Calculates Teale Mechanical Specific Energy and diagnoses drilling dysfunctions:
- **Bit Balling**: High WOB, low ROP, low mechanical efficiency ($< 20\%$).
- **Stick-Slip Vibration**: High torque standard deviation ($\sigma_T / \bar{T} > 35\%$).

### 4.8 Online Bayesian Parameter Auto-Calibration
A recursive Bayesian filter continuously calibrates downhole open-hole friction factor multipliers ($f_{\text{mult}}$) and drillpipe roughness using streaming PWD annular pressure and surface SPP telemetry.

---

## 5. Real-Time Driller Console Web Dashboard & API

The core includes an asynchronous FastAPI backend and a responsive dark-mode Web Dashboard served directly at `http://localhost:8000`:
- **Real-Time Physics Residual Strip Chart**: 1Hz streaming visualization of $\Delta \text{SPP}$ and $\Delta \text{Flow}$ with confidence bands.
- **Drilling Margin Window**: Continuous depth profile of Pore Pressure, Dynamic ECD, and Fracture Gradient.
- **Hook Load Broomstick Charts**: Pick-up, Slack-off, and Rotating off-bottom curves.
- **Safe Tripping Envelope Gauges**: Dynamic POOH and RIH speed limits.
- **Automated Kill Sheet Card**: Live ICP/FCP, MAASP, and step-down schedules.
- **Active Alert Banner**: Instant visual warnings for kick precursors, pack-offs, and washouts with drill floor actions.

To launch the live dashboard:
```bash
uvicorn rig_twin.server:app --host 0.0.0.0 --port 8000
```

---

## 6. Repository Structure

```
rig-digital-twin-core/
├── pyproject.toml              # Build metadata and dependency specifications
├── README.md                   # Complete architectural documentation
├── docker-compose.yml          # TimescaleDB PostgreSQL-16 service
├── sql/
│   └── 001_timescaledb_hypertables.sql  # Hypertable DDL, compression & rollup views
├── rig_twin/
│   ├── core/
│   │   ├── __init__.py
│   │   └── models.py           # Domain models: Well, Fluid, Telemetry, Baselines, Alerts
│   ├── physics/
│   │   ├── __init__.py
│   │   ├── rheology.py         # Herschel-Bulkley, Bingham, Power-Law & Reynolds engines
│   │   ├── hydraulics.py       # Pipe/annulus frictional loss, bit nozzles, SPP, ECD
│   │   ├── surge_swab.py       # Burkhardt & Lubinski dynamic tripping kinematics
│   │   └── engine.py           # RigPhysicsEngine orchestrator
│   ├── ml/
│   │   ├── __init__.py
│   │   ├── estimator.py        # Physics-residual Kalman state estimator & CUSUM detector
│   │   └── kick_detector.py    # Precursor kick, swab risk, pack-off, and washout rules
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── witsml_parser.py    # WITSML XML 1.3.1/1.4.1 & JSON stream normalizer
│   │   └── stream_processor.py # Continuous background pipeline coupling Physics + ML
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── schema.py           # SQLAlchemy TimescaleDB hypertable ORM models
│   │   └── repository.py       # High-throughput batch writer and query repository
│   └── demo.py                 # Interactive real-time simulation demo
└── tests/
    ├── test_physics_hydraulics.py
    ├── test_physics_surge_swab.py
    ├── test_witsml_ingestion.py
    ├── test_ml_estimator.py
    ├── test_timeseries_persistence.py
    └── test_end_to_end_twin.py
```

---

## 5. Quickstart & Installation

### Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Docker & Docker Compose (optional, for live TimescaleDB server)

### 1. Environment Setup
```bash
git clone https://github.com/example/rig-digital-twin-core.git
cd rig-digital-twin-core

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Run the Test Suite
Execute the 22 comprehensive unit and integration tests:
```bash
pytest -v
```

### 3. Run the Real-Time Simulation Demo
Demonstrates real-time telemetry processing, physics hydraulics baseline generation, gas influx kick precursor detection, and tripping swab risk analysis:
```bash
python -m rig_twin.demo
```

### 4. (Optional) Launch TimescaleDB Service
```bash
docker compose up -d
```
Connect via `psql`:
```bash
psql -h localhost -p 5432 -U rig_admin -d rig_digital_twin
```

---

## 6. Programmatic Usage Example

```python
from datetime import datetime, timezone
from rig_twin.core.models import (
    WellGeometry, FluidProperties, RheologyModelType,
    TubularSection, DrillStringSection, BitGeometry, TelemetryRecord
)
from rig_twin.ingestion.stream_processor import StreamProcessor
from rig_twin.persistence.repository import TimescaleTwinRepository

# 1. Define Well Geometry & Herschel-Bulkley Fluid
well = WellGeometry(
    well_id="NORTH-SEA-01",
    casing_sections=[
        TubularSection(name="9-5/8 Casing", top_depth_ft=0, bottom_depth_ft=9500, inner_diameter_in=8.681),
        TubularSection(name="8-1/2 Open Hole", top_depth_ft=9500, bottom_depth_ft=12000, inner_diameter_in=8.5, is_open_hole=True)
    ],
    drillstring_sections=[
        DrillStringSection(name="5-in Drillpipe", length_ft=11400, outer_diameter_in=5.0, inner_diameter_in=4.276),
        DrillStringSection(name="6-1/2 Drill Collars", length_ft=600, outer_diameter_in=6.5, inner_diameter_in=2.813)
    ],
    bit=BitGeometry(diameter_in=8.5, nozzle_sizes_32nds=[12, 12, 12])
)

fluid = FluidProperties(
    density_ppg=11.2,
    model_type=RheologyModelType.HERSCHEL_BULKLEY,
    yield_stress_lbf_100sqft=9.5,
    k_consistency=0.48,
    n_flow_index=0.62
)

# 2. Initialize Stream Processor with TimescaleDB
repo = TimescaleTwinRepository("sqlite:///:memory:")  # Or postgresql://user:pass@localhost:5432/rig_digital_twin
twin = StreamProcessor(geometry=well, fluid=fluid, repository=repo, pore_pressure_ppg=10.6)

# 3. Ingest Streaming Telemetry Record
telemetry = TelemetryRecord(
    timestamp=datetime.now(timezone.utc),
    well_id="NORTH-SEA-01",
    measured_depth_ft=11500.0,
    true_vertical_depth_ft=11500.0,
    bit_depth_ft=11500.0,
    hole_depth_ft=11500.0,
    flow_rate_in_gpm=520.0,
    flow_rate_out_gpm=542.0,  # +22 gpm influx
    standpipe_pressure_psi=4070.0,
    pit_rate_of_change_bbl_hr=8.5
)

physics, anomaly = twin.process_record(telemetry)

print(f"Physics SPP: {physics.total_predicted_spp_psi:.1f} psi | Dynamic ECD: {physics.dynamic_ecd_ppg:.2f} ppg")
print(f"Alert: {anomaly.classification.value} (Severity: {anomaly.severity.value})")
print(f"Diagnostic: {anomaly.diagnostic_message}")
```

---

## 7. License
Apache 2.0. Built for production drilling engineering and digital twin research.
