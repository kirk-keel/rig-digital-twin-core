"""End-to-end runnable demonstration of Rig Digital Twin Core.

Simulates real-time drilling telemetry, computes coupled physics baselines,
detects kick precursors before surface tank gain registers, and logs to TimescaleDB/SQLite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random
import time
from rig_twin.core.models import (
    BitGeometry,
    DrillStringSection,
    FluidProperties,
    RheologyModelType,
    TelemetryRecord,
    TubularSection,
    WellGeometry,
)
from rig_twin.ingestion.stream_processor import StreamProcessor
from rig_twin.persistence.repository import TimescaleTwinRepository


def build_sample_well() -> Tuple[WellGeometry, FluidProperties]:
    """Construct a typical 12,000 ft vertical/deviated offshore well geometry."""
    casing = [
        TubularSection(
            name="Surface Casing 13-3/8\"",
            top_depth_ft=0.0,
            bottom_depth_ft=4500.0,
            inner_diameter_in=12.415,
            is_open_hole=False,
            friction_factor_multiplier=1.0,
        ),
        TubularSection(
            name="Intermediate Casing 9-5/8\"",
            top_depth_ft=4500.0,
            bottom_depth_ft=9500.0,
            inner_diameter_in=8.681,
            is_open_hole=False,
            friction_factor_multiplier=1.05,
        ),
        TubularSection(
            name="Open Hole 8-1/2\"",
            top_depth_ft=9500.0,
            bottom_depth_ft=12000.0,
            inner_diameter_in=8.500,
            is_open_hole=True,
            friction_factor_multiplier=1.2,
        ),
    ]

    drillstring = [
        DrillStringSection(
            name="5\" Drill Pipe",
            length_ft=10800.0,
            outer_diameter_in=5.0,
            inner_diameter_in=4.276,
        ),
        DrillStringSection(
            name="5\" Heavy Weight Drill Pipe (HWDP)",
            length_ft=600.0,
            outer_diameter_in=5.0,
            inner_diameter_in=3.0,
        ),
        DrillStringSection(
            name="6-1/2\" Drill Collars & BHA",
            length_ft=600.0,
            outer_diameter_in=6.5,
            inner_diameter_in=2.813,
        ),
    ]

    bit = BitGeometry(
        diameter_in=8.5,
        nozzle_sizes_32nds=[12.0, 12.0, 12.0],  # 3 x 12/32" nozzles -> TFA = 0.331 sq in
    )

    well = WellGeometry(
        well_id="NORTH-SEA-APEX-01",
        casing_sections=casing,
        drillstring_sections=drillstring,
        bit=bit,
    )

    # 11.2 ppg Herschel-Bulkley Drilling Fluid
    fluid = FluidProperties(
        density_ppg=11.2,
        model_type=RheologyModelType.HERSCHEL_BULKLEY,
        yield_stress_lbf_100sqft=9.5,
        k_consistency=0.48,
        n_flow_index=0.62,
        pv_cp=18.0,
        yp_lbf_100sqft=14.0,
    )

    return well, fluid


def run_simulation_demo() -> None:
    """Run an automated streaming simulation demonstrating kick precursor and swab detection."""
    print("================================================================================")
    print(" RIG DIGITAL TWIN CORE - COUPLED PHYSICS & ML STATE ESTIMATOR")
    print("================================================================================")

    well, fluid = build_sample_well()
    repo = TimescaleTwinRepository("sqlite:///:memory:")

    alerts_triggered = []

    def on_alert(alert):
        alerts_triggered.append(alert)
        print(f"\n[🚨 ALERT TRIGGERED] Time: {alert.timestamp.strftime('%H:%M:%S')} | Severity: {alert.severity.value}")
        print(f" -> Classification: {alert.classification.value}")
        print(f" -> Diagnostic: {alert.diagnostic_message}")
        print(f" -> Action: {alert.recommended_action}")
        print(f" -> SPP Residual: {alert.spp_residual_psi:+.1f} psi | Flow Residual: {alert.flow_residual_gpm:+.1f} gpm\n")

    twin = StreamProcessor(
        geometry=well,
        fluid=fluid,
        repository=repo,
        alert_callback=on_alert,
        pore_pressure_ppg=10.6,
        fracture_pressure_ppg=14.2,
    )

    base_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    current_depth = 11450.0

    print(f"Initializing Well: {well.well_id} (Bit TFA: {well.bit.total_flow_area_sq_in:.3f} sq.in)")
    print(f"Mud Weight: {fluid.density_ppg} ppg | Rheology Model: {fluid.model_type.value}")
    print("-" * 80)

    # Phase 1: Steady Drilling (Normal state, 7 steps)
    print(">>> PHASE 1: Normal Drilling Operations (Circulating 520 gpm)...")
    for step in range(1, 8):
        t = base_time + timedelta(seconds=step * 5)
        current_depth += 0.3
        
        # Observed SPP tracks theoretical ~4085 psi closely (+/- noise)
        record = TelemetryRecord(
            timestamp=t,
            well_id=well.well_id,
            measured_depth_ft=current_depth,
            true_vertical_depth_ft=current_depth,
            bit_depth_ft=current_depth,
            hole_depth_ft=current_depth,
            flow_rate_in_gpm=520.0,
            flow_rate_out_gpm=520.0 + random.uniform(-1.5, 1.5),
            standpipe_pressure_psi=4085.0 + random.uniform(-5.0, 5.0),
            surface_rpm=120.0,
            surface_torque_ft_lbf=8500.0,
            mud_weight_in_ppg=11.2,
            mud_weight_out_ppg=11.2,
            pit_volume_total_bbl=520.0,
            pit_rate_of_change_bbl_hr=0.0,
        )

        phys, anom = twin.process_record(record)
        print(
            f"[{t.strftime('%H:%M:%S')}] Depth: {record.measured_depth_ft:.1f} ft | "
            f"SPP (Obs/Phys): {record.standpipe_pressure_psi:.0f}/{phys.total_predicted_spp_psi:.0f} psi | "
            f"ECD: {phys.dynamic_ecd_ppg:.2f} ppg | "
            f"Status: {anom.classification.value}"
        )

    # Phase 2: Kick Precursor (Formation fluid entering wellbore)
    print("\n>>> PHASE 2: Incipient Gas Influx / Kick Precursor Scenario...")
    print(">> Note: Pit volume switch has NOT tripped yet (+0.4 bbl gain).")
    print(">> Deterministic mass balance + residual filter flags delta-flow discrepancy in real-time.")

    for step in range(8, 14):
        t = base_time + timedelta(seconds=step * 5)
        current_depth += 0.3
        influx_extra_flow = (step - 7) * 4.5  # Influx flow expands: +4.5, +9.0, +13.5, +18.0...
        
        record = TelemetryRecord(
            timestamp=t,
            well_id=well.well_id,
            measured_depth_ft=current_depth,
            true_vertical_depth_ft=current_depth,
            bit_depth_ft=current_depth,
            hole_depth_ft=current_depth,
            flow_rate_in_gpm=520.0,
            flow_rate_out_gpm=520.0 + influx_extra_flow,
            standpipe_pressure_psi=4085.0 - (step - 7) * 3.0,  # Slight drop as gas displaces mud
            surface_rpm=120.0,
            surface_torque_ft_lbf=8500.0,
            mud_weight_in_ppg=11.2,
            mud_weight_out_ppg=11.0,
            pit_volume_total_bbl=520.0 + (step - 7) * 0.15,
            pit_rate_of_change_bbl_hr=(step - 7) * 1.8,
        )

        phys, anom = twin.process_record(record)
        print(
            f"[{t.strftime('%H:%M:%S')}] Flow Out: {record.flow_rate_out_gpm:.1f} gpm "
            f"(Delta: {record.delta_flow_gpm:+.1f} gpm) | "
            f"Status: {anom.classification.value} (Score: {anom.anomaly_score:.2f})"
        )

    # Phase 3: Swab Risk during Tripping Out of Hole
    print("\n>>> PHASE 3: POOH (Pulling Out of Hole) Swab Underbalance Scenario...")
    twin.anomaly_detector.pore_pressure_ppg = 10.95  # Local permeable gas sand pore pressure
    print(f">> Critical gas zone formation pore pressure: {twin.anomaly_detector.pore_pressure_ppg:.2f} ppg")
    tripping_speeds = [-45.0, -95.0, -145.0]  # ft/min pulling speed
    for i, speed in enumerate(tripping_speeds):
        t = base_time + timedelta(seconds=(15 + i) * 5)
        current_depth -= 30.0

        record = TelemetryRecord(
            timestamp=t,
            well_id=well.well_id,
            measured_depth_ft=current_depth,
            true_vertical_depth_ft=current_depth,
            bit_depth_ft=current_depth,
            hole_depth_ft=11455.0,
            string_velocity_ft_min=speed,
            flow_rate_in_gpm=0.0,
            flow_rate_out_gpm=0.0,
            standpipe_pressure_psi=0.0,
            surface_rpm=0.0,
            surface_torque_ft_lbf=0.0,
            mud_weight_in_ppg=11.2,
            mud_weight_out_ppg=11.2,
            pit_volume_total_bbl=521.0,
            pit_rate_of_change_bbl_hr=0.0,
        )

        phys, anom = twin.process_record(record)
        print(
            f"[{t.strftime('%H:%M:%S')}] Trip Speed: {speed:.0f} ft/min | "
            f"Swab Drop: {phys.swab_pressure_loss_psi:.1f} psi | "
            f"Effective Swab ECD: {phys.effective_ecd_swab_ppg:.2f} ppg vs Pore Pressure {twin.anomaly_detector.pore_pressure_ppg:.2f} ppg | "
            f"Status: {anom.classification.value}"
        )

    print("\n" + "=" * 80)
    print(f" DEMO COMPLETE: {len(alerts_triggered)} Anomaly Alerts Successfully Detected & Logged")
    print("=" * 80)


if __name__ == "__main__":
    run_simulation_demo()
