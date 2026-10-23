-- TimescaleDB Hypertables Schema for Rig Digital Twin Core
-- Enables high-throughput ingestion, compression, and fast analytical time-series queries.

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- 1. Raw Telemetry Hypertable
CREATE TABLE IF NOT EXISTS telemetry_records (
    time TIMESTAMPTZ NOT NULL,
    well_id VARCHAR(64) NOT NULL,
    measured_depth_ft DOUBLE PRECISION NOT NULL,
    true_vertical_depth_ft DOUBLE PRECISION NOT NULL,
    bit_depth_ft DOUBLE PRECISION NOT NULL,
    hole_depth_ft DOUBLE PRECISION NOT NULL,
    string_velocity_ft_min DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    flow_rate_in_gpm DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    flow_rate_out_gpm DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    standpipe_pressure_psi DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    downhole_annular_pressure_psi DOUBLE PRECISION,
    downhole_ecd_ppg DOUBLE PRECISION,
    hook_load_klbf DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    surface_rpm DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    surface_torque_ft_lbf DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    mud_weight_in_ppg DOUBLE PRECISION NOT NULL DEFAULT 10.0,
    mud_weight_out_ppg DOUBLE PRECISION NOT NULL DEFAULT 10.0,
    pit_volume_total_bbl DOUBLE PRECISION NOT NULL DEFAULT 500.0,
    pit_rate_of_change_bbl_hr DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    PRIMARY KEY (time, well_id, measured_depth_ft)
);

-- Convert to hypertable partitioned on time (chunk size: 1 day)
SELECT create_hypertable('telemetry_records', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

CREATE INDEX IF NOT EXISTS idx_telemetry_well_time ON telemetry_records (well_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_well_depth ON telemetry_records (well_id, measured_depth_ft DESC);

-- Enable TimescaleDB columnar compression
ALTER TABLE telemetry_records SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'well_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('telemetry_records', INTERVAL '7 days', if_not_exists => TRUE);


-- 2. Deterministic Physics Baselines Hypertable
CREATE TABLE IF NOT EXISTS physics_baselines (
    time TIMESTAMPTZ NOT NULL,
    well_id VARCHAR(64) NOT NULL,
    measured_depth_ft DOUBLE PRECISION NOT NULL,
    hydrostatic_pressure_psi DOUBLE PRECISION NOT NULL,
    annular_pressure_loss_psi DOUBLE PRECISION NOT NULL,
    pipe_internal_pressure_loss_psi DOUBLE PRECISION NOT NULL,
    bit_pressure_loss_psi DOUBLE PRECISION NOT NULL,
    total_predicted_spp_psi DOUBLE PRECISION NOT NULL,
    static_ecd_ppg DOUBLE PRECISION NOT NULL,
    dynamic_ecd_ppg DOUBLE PRECISION NOT NULL,
    surge_pressure_loss_psi DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    swab_pressure_loss_psi DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    effective_ecd_surge_ppg DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    effective_ecd_swab_ppg DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    annulus_flow_regime VARCHAR(32) NOT NULL,
    pipe_flow_regime VARCHAR(32) NOT NULL,
    bit_jet_impact_force_lbf DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    bit_hydraulic_horsepower_hhp DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    PRIMARY KEY (time, well_id, measured_depth_ft)
);

SELECT create_hypertable('physics_baselines', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

CREATE INDEX IF NOT EXISTS idx_physics_well_time ON physics_baselines (well_id, time DESC);


-- 3. Machine Learning Residuals & Anomaly Events Hypertable
CREATE TABLE IF NOT EXISTS anomaly_events (
    time TIMESTAMPTZ NOT NULL,
    well_id VARCHAR(64) NOT NULL,
    measured_depth_ft DOUBLE PRECISION NOT NULL,
    classification VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    anomaly_score DOUBLE PRECISION NOT NULL,
    spp_residual_psi DOUBLE PRECISION NOT NULL,
    flow_residual_gpm DOUBLE PRECISION NOT NULL,
    ecd_residual_ppg DOUBLE PRECISION,
    pit_residual_bbl_min DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    detection_rule VARCHAR(128) NOT NULL,
    diagnostic_message TEXT NOT NULL,
    recommended_action TEXT,
    PRIMARY KEY (time, well_id, measured_depth_ft)
);

SELECT create_hypertable('anomaly_events', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

CREATE INDEX IF NOT EXISTS idx_anomalies_well_time ON anomaly_events (well_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON anomaly_events (severity, time DESC);


-- 4. Continuous Aggregate View: 1-Minute Drilling State Rollup
CREATE MATERIALIZED VIEW IF NOT EXISTS drilling_minute_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    well_id,
    AVG(standpipe_pressure_psi) AS avg_spp_psi,
    AVG(flow_rate_in_gpm) AS avg_flow_in_gpm,
    AVG(flow_rate_out_gpm) AS avg_flow_out_gpm,
    AVG(flow_rate_out_gpm - flow_rate_in_gpm) AS avg_delta_flow_gpm,
    MAX(pit_volume_total_bbl) - MIN(pit_volume_total_bbl) AS pit_volume_delta_bbl,
    MAX(measured_depth_ft) AS max_depth_ft
FROM telemetry_records
GROUP BY bucket, well_id;

SELECT add_continuous_aggregate_policy('drilling_minute_summary',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);
