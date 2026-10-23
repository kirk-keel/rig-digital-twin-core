"""Unit tests for petroleum rheology and wellbore hydraulics physics."""

import pytest
import math
from rig_twin.core.models import (
    BitGeometry,
    DrillStringSection,
    FluidProperties,
    RheologyModelType,
    TubularSection,
    WellGeometry,
)
from rig_twin.physics.rheology import RheologyEngine
from rig_twin.physics.hydraulics import HydraulicsEngine


@pytest.fixture
def sample_fluid():
    return FluidProperties(
        density_ppg=12.0,
        model_type=RheologyModelType.HERSCHEL_BULKLEY,
        yield_stress_lbf_100sqft=10.0,
        k_consistency=0.50,
        n_flow_index=0.60,
        pv_cp=20.0,
        yp_lbf_100sqft=15.0,
    )


@pytest.fixture
def sample_well():
    casing = [
        TubularSection(
            name="Casing 9-5/8\"",
            top_depth_ft=0.0,
            bottom_depth_ft=8000.0,
            inner_diameter_in=8.681,
        ),
        TubularSection(
            name="Open Hole 8-1/2\"",
            top_depth_ft=8000.0,
            bottom_depth_ft=10000.0,
            inner_diameter_in=8.500,
            is_open_hole=True,
        ),
    ]
    drillstring = [
        DrillStringSection(
            name="5\" DP",
            length_ft=9400.0,
            outer_diameter_in=5.0,
            inner_diameter_in=4.276,
        ),
        DrillStringSection(
            name="6-1/2\" DC",
            length_ft=600.0,
            outer_diameter_in=6.5,
            inner_diameter_in=2.813,
        ),
    ]
    bit = BitGeometry(
        diameter_in=8.5,
        nozzle_sizes_32nds=[12.0, 12.0, 12.0],
    )
    return WellGeometry(
        well_id="TEST-WELL-01",
        casing_sections=casing,
        drillstring_sections=drillstring,
        bit=bit,
    )


def test_rheology_shear_stress(sample_fluid):
    engine = RheologyEngine(sample_fluid)
    gamma = 511.0  # standard Fann 35 shear rate
    tau = engine.shear_stress(gamma)
    assert tau > sample_fluid.yield_stress_lbf_100sqft
    mu_eff = engine.apparent_viscosity_cp(gamma)
    assert mu_eff > 0.0


def test_rheology_models_comparison():
    rate = 170.0
    # Bingham
    bf = FluidProperties(density_ppg=10.0, model_type=RheologyModelType.BINGHAM_PLASTIC, pv_cp=15.0, yp_lbf_100sqft=10.0)
    b_engine = RheologyEngine(bf)
    tau_b = b_engine.shear_stress(rate)
    assert tau_b > 10.0

    # Power Law
    pf = FluidProperties(density_ppg=10.0, model_type=RheologyModelType.POWER_LAW, k_consistency=0.4, n_flow_index=0.65)
    p_engine = RheologyEngine(pf)
    tau_p = p_engine.shear_stress(rate)
    assert tau_p > 0.0


def test_hydrostatic_pressure(sample_well, sample_fluid):
    hydraulics = HydraulicsEngine(sample_well, sample_fluid)
    # P = 0.052 * 12.0 * 10000 = 6240 psi
    p_hydro = hydraulics.hydrostatic_pressure_psi(10000.0)
    assert math.isclose(p_hydro, 6240.0, rel_tol=1e-3)


def test_bit_hydraulics(sample_well, sample_fluid):
    hydraulics = HydraulicsEngine(sample_well, sample_fluid)
    q = 500.0
    dp_bit, v_jet, hhp, f_imp = hydraulics.bit_pressure_loss_psi(q, sample_well.bit)

    assert dp_bit > 500.0
    assert v_jet > 100.0
    assert hhp > 100.0
    assert f_imp > 500.0


def test_pipe_and_annular_losses(sample_well, sample_fluid):
    hydraulics = HydraulicsEngine(sample_well, sample_fluid)
    q = 550.0
    depth = 10000.0

    p_pipe, pipe_details = hydraulics.pipe_internal_losses_psi(q, depth)
    assert p_pipe > 500.0
    assert len(pipe_details) == 2

    apl, ann_details, regime = hydraulics.annular_pressure_loss_psi(q, depth)
    assert apl > 100.0
    assert regime in ["LAMINAR", "TURBULENT", "TRANSITIONAL"]

    ecd = hydraulics.equivalent_circulating_density_ppg(apl, depth)
    assert ecd > sample_fluid.density_ppg
