"""Unit tests for tripping dynamics, surge pressure, and swab pressure."""

import pytest
from rig_twin.core.models import (
    BitGeometry,
    DrillStringSection,
    FluidProperties,
    RheologyModelType,
    TubularSection,
    WellGeometry,
)
from rig_twin.physics.surge_swab import SurgeSwabEngine


@pytest.fixture
def tripping_setup():
    casing = [
        TubularSection(
            name="Casing",
            top_depth_ft=0.0,
            bottom_depth_ft=10000.0,
            inner_diameter_in=8.681,
        )
    ]
    drillstring = [
        DrillStringSection(
            name="5\" DP",
            length_ft=10000.0,
            outer_diameter_in=5.0,
            inner_diameter_in=4.276,
        )
    ]
    well = WellGeometry(
        well_id="TRIP-WELL",
        casing_sections=casing,
        drillstring_sections=drillstring,
        bit=BitGeometry(),
    )
    fluid = FluidProperties(
        density_ppg=11.5,
        model_type=RheologyModelType.HERSCHEL_BULKLEY,
        yield_stress_lbf_100sqft=8.0,
        k_consistency=0.45,
        n_flow_index=0.65,
    )
    return well, fluid


def test_clinging_constant(tripping_setup):
    well, fluid = tripping_setup
    engine = SurgeSwabEngine(well, fluid)
    kc = engine.clinging_constant(hole_diam_in=8.681, pipe_od_in=5.0)
    assert 0.25 <= kc <= 0.55


def test_surge_pressure_on_rih(tripping_setup):
    well, fluid = tripping_setup
    engine = SurgeSwabEngine(well, fluid)

    # Tripping in at 90 ft/min
    surge, swab = engine.calculate_surge_swab_psi(
        string_velocity_ft_min=90.0,
        bit_depth_ft=10000.0,
        is_float_closed=True,
    )
    assert surge > 50.0
    assert swab == 0.0


def test_swab_pressure_on_pooh(tripping_setup):
    well, fluid = tripping_setup
    engine = SurgeSwabEngine(well, fluid)

    # Pulling out of hole at -90 ft/min
    surge, swab = engine.calculate_surge_swab_psi(
        string_velocity_ft_min=-90.0,
        bit_depth_ft=10000.0,
        is_float_closed=True,
    )
    assert surge == 0.0
    assert swab > 50.0


def test_stationary_string_zero_surge_swab(tripping_setup):
    well, fluid = tripping_setup
    engine = SurgeSwabEngine(well, fluid)
    surge, swab = engine.calculate_surge_swab_psi(
        string_velocity_ft_min=0.0,
        bit_depth_ft=10000.0,
    )
    assert surge == 0.0
    assert swab == 0.0
