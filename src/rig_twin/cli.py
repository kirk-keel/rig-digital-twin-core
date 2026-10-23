"""Rig Digital Twin Core - Unified Command Line Interface (CLI)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
import uvicorn

from rig_twin.core.models import TelemetryRecord
from rig_twin.core.report_exporter import IncidentReportExporter
from rig_twin.demo import build_sample_well, run_simulation_demo
from rig_twin.physics.casing_wear import CasingWearAndFatigueEngine
from rig_twin.physics.geopressure import GeopressureEngine
from rig_twin.physics.trajectory import DirectionalTrajectoryEngine, SurveyStation
from rig_twin.physics.transient_hydraulics import TransientHydraulicsEngine
from rig_twin.physics.vibrations import DrillstringDynamicsEngine
from rig_twin.physics.well_control_kill_sheet import WellControlEngine, WellControlInput
from rig_twin.physics.what_if_sandbox import WhatIfSandbox
from rig_twin.ingestion.wits0_parser import Wits0TcpServer


def cli_serve(args: argparse.Namespace) -> None:
    """Start FastAPI server and Driller Web Console."""
    print(f"Starting Rig Digital Twin Core server on http://{args.host}:{args.port}")
    uvicorn.run("rig_twin.server:app", host=args.host, port=args.port, reload=args.reload)


def cli_sim(args: argparse.Namespace) -> None:
    """Run interactive terminal simulation."""
    run_simulation_demo()


def cli_kill_sheet(args: argparse.Namespace) -> None:
    """Compute automated well control kill sheet."""
    inputs = WellControlInput(
        well_id=args.well_id,
        current_mud_weight_ppg=args.mw,
        true_vertical_depth_ft=args.tvd,
        measured_depth_ft=args.md or args.tvd,
        shut_in_drillpipe_pressure_psi=args.sidpp,
        shut_in_casing_pressure_psi=args.sicp,
        slow_circulating_pressure_psi=args.scr,
        pit_gain_bbl=args.pit_gain,
        casing_shoe_tvd_ft=args.shoe_tvd,
        leak_off_test_emw_ppg=args.lot,
    )
    engine = WellControlEngine(inputs)
    result = engine.generate_kill_sheet()

    print("=" * 80)
    print(f" WELL CONTROL KILL SHEET - {result.well_id} (API RP 59 / IADC)")
    print("=" * 80)
    print(f" Current Mud Weight:              {result.current_mud_weight_ppg:.2f} ppg")
    print(f" REQUIRED KILL MUD WEIGHT (KMW):  {result.kill_mud_weight_ppg:.2f} ppg")
    print(f" Initial Circulating Press (ICP): {result.initial_circulating_pressure_psi:.1f} psi")
    print(f" Final Circulating Press (FCP):   {result.final_circulating_pressure_psi:.1f} psi")
    print(f" Initial MAASP:                   {result.initial_maasp_psi:.1f} psi")
    print(f" Kill Mud MAASP:                  {result.kill_maasp_psi:.1f} psi")
    print(f" Influx Estimate:                 {result.influx_type_estimate} ({result.influx_gradient_psi_ft:.3f} psi/ft)")
    print(f" Surface to Bit:                  {result.surface_to_bit_volume_bbl:.1f} bbl ({result.surface_to_bit_strokes} strokes)")
    print(f" Bit to Surface:                  {result.bit_to_surface_volume_bbl:.1f} bbl ({result.bit_to_surface_strokes} strokes)")
    print(f" Total Well Volume:               {result.total_well_strokes} strokes")
    print("-" * 80)
    print(" DRILLPIPE PRESSURE STEP-DOWN SCHEDULE:")
    print("  Strokes   |  Progress  |  Drillpipe Pressure (psi)")
    print(" -----------+------------+--------------------------")
    for s in result.step_down_schedule:
        print(f"  {s['strokes']:<9} |  {s['kill_mud_progress_pct']:>6.1f}%   |  {s['drillpipe_pressure_psi']:.1f} psi")
    print("=" * 80)


def cli_trajectory(args: argparse.Namespace) -> None:
    """Calculate 3D wellbore trajectory via Minimum Curvature Method."""
    engine = DirectionalTrajectoryEngine()
    # Default sample S-curve or J-curve stations if none provided
    stations = [
        SurveyStation(measured_depth_ft=0.0, inclination_deg=0.0, azimuth_deg=45.0),
        SurveyStation(measured_depth_ft=3000.0, inclination_deg=0.0, azimuth_deg=45.0),
        SurveyStation(measured_depth_ft=5000.0, inclination_deg=25.0, azimuth_deg=45.0),
        SurveyStation(measured_depth_ft=8000.0, inclination_deg=35.0, azimuth_deg=65.0),
        SurveyStation(measured_depth_ft=11500.0, inclination_deg=35.0, azimuth_deg=65.0),
    ]
    points = engine.compute_trajectory(stations)

    print("=" * 90)
    print(" 3D DIRECTIONAL TRAJECTORY - MINIMUM CURVATURE METHOD (API STANDARD)")
    print("=" * 90)
    print(f" {'MD (ft)':<10} {'Inc (deg)':<10} {'Azi (deg)':<10} {'TVD (ft)':<10} {'North (ft)':<12} {'East (ft)':<12} {'DLS (deg/100ft)':<15}")
    print("-" * 90)
    for p in points:
        print(f" {p.measured_depth_ft:<10.1f} {p.inclination_deg:<10.1f} {p.azimuth_deg:<10.1f} {p.true_vertical_depth_ft:<10.1f} {p.northing_ft:<12.1f} {p.easting_ft:<12.1f} {p.dogleg_severity_deg_100ft:<15.2f}")
    print("=" * 90)


def cli_geopressure(args: argparse.Namespace) -> None:
    """Predict pore pressure and fracture gradient using Eaton's method."""
    engine = GeopressureEngine()
    res = engine.predict_pressures(
        tvd_ft=args.tvd,
        rop_ft_hr=args.rop,
        rpm=args.rpm,
        wob_klbf=args.wob,
        bit_diameter_in=args.bit_diam,
        current_mud_weight_ppg=args.mw,
    )
    print("=" * 80)
    print(f" DYNAMIC GEOPRESSURE & FRACTURE GRADIENT (TVD: {args.tvd:.1f} ft)")
    print("=" * 80)
    print(f" Corrected d-exponent (d_xc):     {res.d_exponent_corrected:.3f} (Normal: {res.normal_compaction_d_exp:.3f})")
    print(f" PORE PRESSURE (Pp):              {res.pore_pressure_ppg:.2f} ppg ({res.pore_pressure_psi:.1f} psi)")
    print(f" FRACTURE GRADIENT (Fg):          {res.fracture_gradient_ppg:.2f} ppg ({res.fracture_gradient_psi:.1f} psi)")
    print(f" Overburden Stress:               {res.overburden_gradient_ppg:.2f} ppg")
    print(f" Overpressured Status:            {'⚠️ YES - TRANSITION ZONE' if res.is_overpressured else '✅ NORMAL PRESSURE'}")
    print("=" * 80)


def cli_wits0(args: argparse.Namespace) -> None:
    """Start TCP WITS Level 0 ingestion server."""
    print(f"Starting WITS Level 0 TCP stream server on {args.host}:{args.port}...")
    server = Wits0TcpServer(host=args.host, port=args.port, record_callback=lambda r: print(f"[WITS0 INGEST] Bit Depth: {r.bit_depth_ft:.1f} ft | SPP: {r.standpipe_pressure_psi:.1f} psi"))
    try:
        asyncio.run(server.start())
        print(f"WITS0 TCP Server listening on port {args.port}. Press Ctrl+C to terminate.")
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        print("\nStopping WITS0 server.")
        asyncio.run(server.stop())


def cli_vibrations(args: argparse.Namespace) -> None:
    """Evaluate BHA vibrations and resonance bands."""
    engine = DrillstringDynamicsEngine(drillstring_length_ft=args.length, stabilizer_spacing_ft=args.span)
    res = engine.evaluate_safe_operating_rpm_bands()
    print("=" * 80)
    print(f" DRILLSTRING & BHA VIBRATION MODAL ANALYSIS (Length: {args.length:.0f} ft)")
    print("=" * 80)
    print(f" Axial Bit Bounce Natural Frequency:     {res.axial_bit_bounce_natural_freq_hz:.3f} Hz (Critical: {res.axial_critical_rpm:.1f} RPM)")
    print(f" Torsional Stick-Slip Natural Frequency: {res.torsional_stick_slip_natural_freq_hz:.3f} Hz (Critical: {res.torsional_critical_rpm:.1f} RPM)")
    print(f" BHA Lateral Forward Whirl:              {res.forward_whirl_critical_rpm:.1f} RPM")
    print(f" BHA Lateral Backward Whirl:             {res.backward_whirl_critical_rpm:.1f} RPM")
    print("-" * 80)
    print(" SAFE OPERATING RPM WINDOWS:")
    for w in res.safe_rpm_windows:
        print(f"  ✅ {w[0]:.0f} to {w[1]:.0f} RPM")
    print("-" * 80)
    print(" DANGEROUS RESONANCE BANDS:")
    for b in res.resonance_bands:
        print(f"  ❌ [{b.severity}] {b.mode:<16} (Center: {b.center_rpm:.0f} RPM, Range: {b.min_rpm:.0f} - {b.max_rpm:.0f} RPM)")
    print("=" * 80)


def cli_waterhammer(args: argparse.Namespace) -> None:
    """Simulate hydraulic waterhammer transient surge pressure."""
    well, fluid = build_sample_well()
    fluid.density_ppg = args.mw
    engine = TransientHydraulicsEngine(fluid=fluid, well_depth_ft=args.depth)
    res = engine.simulate_valve_closure_surge(flow_rate_gpm=args.flow, valve_closure_time_sec=args.close_time)

    print("=" * 80)
    print(f" TRANSIENT WATERHAMMER JOUKOWSKY SURGE SIMULATOR (Depth: {args.depth:.0f} ft)")
    print("=" * 80)
    print(f" Mud Acoustic Wave Speed:           {res.mud_acoustic_speed_fps:.1f} ft/s")
    print(f" Round-Trip Travel Time (2L/c):     {res.round_trip_acoustic_time_sec:.3f} sec")
    print(f" Valve Closure Time:                {res.closure_time_sec:.3f} sec ({'RAPID SHUT-IN' if res.is_rapid_closure else 'GRADUAL CLOSURE'})")
    print(f" Joukowsky Peak Pressure Surge:     {res.joukowsky_peak_surge_psi:.1f} psi")
    print(f" Effective Surge Pressure at Choke: {res.effective_surge_pressure_psi:.1f} psi")
    print(f" Total Peak Transient Pressure:     {res.total_transient_peak_pressure_psi:.1f} psi")
    print(f" Casing Burst Rating Safety Factor: {res.casing_burst_safety_factor:.2f}")
    print(f" Casing Burst Limit Compromised:    {'⚠️ YES - SURGE THREATENS CASING' if res.is_burst_limit_threatened else '✅ NO - WITHIN SAFETY MARGIN'}")
    print("=" * 80)


def cli_what_if(args: argparse.Namespace) -> None:
    """Run an automated what-if operational simulation."""
    well, fluid = build_sample_well()
    tel = TelemetryRecord(
        timestamp=datetime.now(timezone.utc),
        well_id=well.well_id,
        measured_depth_ft=args.depth,
        true_vertical_depth_ft=args.depth,
        bit_depth_ft=args.depth,
        hole_depth_ft=args.depth,
        flow_rate_in_gpm=520.0,
        flow_rate_out_gpm=520.0,
        standpipe_pressure_psi=4085.0,
    )
    sandbox = WhatIfSandbox(well, fluid, tel)

    if args.scenario == "flow":
        res = sandbox.simulate_flow_rate_step(target_flow_gpm=args.value)
    elif args.scenario == "mud":
        res = sandbox.simulate_mud_weight_change(target_mud_weight_ppg=args.value)
    elif args.scenario == "trip":
        res = sandbox.simulate_tripping_speed(target_velocity_ft_min=args.value)
    else:
        res = sandbox.simulate_flow_rate_step(target_flow_gpm=args.value)

    print("=" * 80)
    print(f" WHAT-IF OPERATIONAL SIMULATION - [{res.scenario_type}]")
    print("=" * 80)
    print(f" Tested Parameter:          {res.parameter_tested} = {res.hypothetical_value:.1f} (Baseline: {res.baseline_value:.1f})")
    print(f" Predicted Standpipe Press: {res.predicted_spp_psi:.1f} psi")
    print(f" Predicted Dynamic ECD:     {res.predicted_ecd_ppg:.2f} ppg")
    print(f" Safe Execution Status:     {'✅ SAFE TO EXECUTE' if res.is_safe else '⚠️ POTENTIAL HAZARD'}")
    if res.risk_factors:
        for r in res.risk_factors:
            print(f"  ❌ Risk: {r}")
    print(f" Engineering Insights:      {res.engineering_insights}")
    print("=" * 80)


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the command-line argument parser for rig-twin."""
    parser = argparse.ArgumentParser(
        prog="rig-twin",
        description="Rig Digital Twin Core: Real-time simulation, predictive wellbore physics, and autonomous drilling engine",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 1. serve
    p_serve = subparsers.add_parser("serve", help="Launch FastAPI server and Driller Console Web Dashboard")
    p_serve.add_argument("--host", default="0.0.0.0", help="Binding host (default: 0.0.0.0)")
    p_serve.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    p_serve.add_argument("--reload", action="store_true", help="Enable live code reload")

    # 2. sim
    p_sim = subparsers.add_parser("sim", help="Run interactive terminal digital twin simulation")

    # 3. kill-sheet
    p_kill = subparsers.add_parser("kill-sheet", help="Calculate automated IADC/API well control kill sheet")
    p_kill.add_argument("--sidpp", type=float, required=True, help="Shut-in drill pipe pressure in psi")
    p_kill.add_argument("--sicp", type=float, required=True, help="Shut-in casing pressure in psi")
    p_kill.add_argument("--tvd", type=float, required=True, help="Well true vertical depth in ft")
    p_kill.add_argument("--mw", type=float, default=11.2, help="Current mud weight in ppg")
    p_kill.add_argument("--scr", type=float, default=750.0, help="Slow circulating pressure in psi")
    p_kill.add_argument("--pit-gain", type=float, default=18.5, help="Pit volume gain in bbl")
    p_kill.add_argument("--shoe-tvd", type=float, default=9500.0, help="Casing shoe TVD in ft")
    p_kill.add_argument("--lot", type=float, default=14.8, help="Shoe leak-off test in ppg")
    p_kill.add_argument("--md", type=float, default=None, help="Measured depth in ft")
    p_kill.add_argument("--well-id", default="WELL-01", help="Well identifier")

    # 4. trajectory
    p_traj = subparsers.add_parser("trajectory", help="Compute 3D directional trajectory using Minimum Curvature Method")

    # 5. geopressure
    p_geo = subparsers.add_parser("geopressure", help="Predict dynamic pore pressure and fracture gradient via Eaton's method")
    p_geo.add_argument("--tvd", type=float, required=True, help="True vertical depth in ft")
    p_geo.add_argument("--rop", type=float, default=65.0, help="Rate of penetration in ft/hr")
    p_geo.add_argument("--rpm", type=float, default=120.0, help="Rotary speed in RPM")
    p_geo.add_argument("--wob", type=float, default=22.0, help="Weight on bit in klbf")
    p_geo.add_argument("--bit-diam", type=float, default=8.5, help="Bit diameter in inches")
    p_geo.add_argument("--mw", type=float, default=11.2, help="Mud weight in ppg")

    # 6. wits0-server
    p_wits0 = subparsers.add_parser("wits0-server", help="Launch TCP WITS Level 0 streaming server")
    p_wits0.add_argument("--host", default="0.0.0.0", help="Host")
    p_wits0.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")

    # 7. vibrations
    p_vib = subparsers.add_parser("vibrations", help="Evaluate 3-axis BHA vibrations and whirl resonance bands")
    p_vib.add_argument("--length", type=float, default=11450.0, help="Drillstring length in ft")
    p_vib.add_argument("--span", type=float, default=60.0, help="Stabilizer spacing span in ft")

    # 8. waterhammer
    p_wh = subparsers.add_parser("waterhammer", help="Simulate hydraulic transient waterhammer Joukowsky pressure surge")
    p_wh.add_argument("--depth", type=float, default=11450.0, help="Well depth in ft")
    p_wh.add_argument("--flow", type=float, default=520.0, help="Flow rate in gpm")
    p_wh.add_argument("--close-time", type=float, default=0.5, help="Valve closure time in seconds")
    p_wh.add_argument("--mw", type=float, default=11.2, help="Mud weight in ppg")

    # 9. what-if
    p_whatif = subparsers.add_parser("what-if", help="Run automated what-if operational simulation")
    p_whatif.add_argument("--scenario", choices=["flow", "mud", "trip"], default="flow", help="Scenario type")
    p_whatif.add_argument("--value", type=float, required=True, help="Target hypothetical parameter value")
    p_whatif.add_argument("--depth", type=float, default=11450.0, help="Well depth in ft")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "serve": cli_serve,
        "sim": cli_sim,
        "kill-sheet": cli_kill_sheet,
        "trajectory": cli_trajectory,
        "geopressure": cli_geopressure,
        "wits0-server": cli_wits0,
        "vibrations": cli_vibrations,
        "waterhammer": cli_waterhammer,
        "what-if": cli_what_if,
    }

    func = dispatch.get(args.subcommand)
    if func:
        func(args)


if __name__ == "__main__":
    main()
