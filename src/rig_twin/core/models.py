"""Core data structures and domain models for the Rig Digital Twin Core."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RheologyModelType(str, Enum):
    NEWTONIAN = "NEWTONIAN"
    BINGHAM_PLASTIC = "BINGHAM_PLASTIC"
    POWER_LAW = "POWER_LAW"
    HERSCHEL_BULKLEY = "HERSCHEL_BULKLEY"


class FluidProperties(BaseModel):
    """Drilling mud properties and non-Newtonian rheological characterization.
    
    Standard petroleum engineering units:
    - density: ppg (pounds per gallon)
    - yield_point (tau_0 / YP): lbf/100 ft²
    - plastic_viscosity (PV): cP (centipoise)
    - consistency_index (K): lbf·s^n / 100 ft² (or Pa·s^n)
    - flow_behavior_index (n): dimensionless
    """
    density_ppg: float = Field(..., description="Mud density / weight in ppg")
    model_type: RheologyModelType = Field(
        default=RheologyModelType.HERSCHEL_BULKLEY,
        description="Rheology constitutive relationship"
    )
    # Bingham Plastic parameters
    pv_cp: float = Field(default=15.0, description="Plastic Viscosity in cP")
    yp_lbf_100sqft: float = Field(default=12.0, description="Yield Point in lbf/100ft²")
    # Power-law & Herschel-Bulkley parameters
    k_consistency: float = Field(default=0.45, description="Flow consistency index K (lbf*s^n / 100ft²)")
    n_flow_index: float = Field(default=0.65, description="Flow behavior index n (dimensionless, <1 shear thinning)")
    yield_stress_lbf_100sqft: float = Field(default=8.0, description="Herschel-Bulkley yield stress tau_0 in lbf/100ft²")


class TubularSection(BaseModel):
    """Section of casing, liner, or open borehole."""
    name: str
    top_depth_ft: float
    bottom_depth_ft: float
    inner_diameter_in: float
    is_open_hole: bool = False
    friction_factor_multiplier: float = 1.0


class DrillStringSection(BaseModel):
    """Component of the drillstring (drill pipe, HWDP, collars, BHA)."""
    name: str
    length_ft: float
    outer_diameter_in: float
    inner_diameter_in: float


class BitGeometry(BaseModel):
    """Drill bit characteristics including nozzle configuration."""
    diameter_in: float = 8.5
    # Nozzle sizes in 32nds of an inch (e.g. [12, 12, 12] for 3 x 12/32")
    nozzle_sizes_32nds: List[float] = Field(default_factory=lambda: [12.0, 12.0, 12.0])

    @property
    def total_flow_area_sq_in(self) -> float:
        """Calculate Total Flow Area (TFA) in square inches."""
        import math
        return sum(math.pi * (d / 32.0 / 2.0) ** 2 for d in self.nozzle_sizes_32nds)


class WellGeometry(BaseModel):
    """Complete wellbore trajectory and string configuration."""
    well_id: str
    casing_sections: List[TubularSection]
    drillstring_sections: List[DrillStringSection]
    bit: BitGeometry = Field(default_factory=BitGeometry)


class TelemetryRecord(BaseModel):
    """Standardized streaming WITSML telemetry record."""
    timestamp: datetime
    well_id: str
    measured_depth_ft: float
    true_vertical_depth_ft: float
    bit_depth_ft: float
    hole_depth_ft: float
    
    # Kinematics & Hydraulics
    string_velocity_ft_min: float = 0.0  # Positive = RIH (tripping in), Negative = POOH (pulling out)
    flow_rate_in_gpm: float = 0.0
    flow_rate_out_gpm: float = 0.0
    standpipe_pressure_psi: float = 0.0
    downhole_annular_pressure_psi: Optional[float] = None  # PWD sensor if available
    downhole_ecd_ppg: Optional[float] = None
    
    # Rig mechanics
    hook_load_klbf: float = 0.0
    surface_rpm: float = 0.0
    surface_torque_ft_lbf: float = 0.0
    
    # Mud pit telemetry
    mud_weight_in_ppg: float = 10.0
    mud_weight_out_ppg: float = 10.0
    pit_volume_total_bbl: float = 500.0
    pit_rate_of_change_bbl_hr: float = 0.0

    @property
    def delta_flow_gpm(self) -> float:
        """Difference between flow out and flow in."""
        return self.flow_rate_out_gpm - self.flow_rate_in_gpm


class PhysicsBaseline(BaseModel):
    """Deterministic petroleum physics calculation outputs."""
    timestamp: datetime
    well_id: str
    measured_depth_ft: float
    
    # Static & Dynamic Hydrostatics
    hydrostatic_pressure_psi: float
    annular_pressure_loss_psi: float
    pipe_internal_pressure_loss_psi: float
    bit_pressure_loss_psi: float
    total_predicted_spp_psi: float
    
    # Equivalent Circulating Density
    static_ecd_ppg: float
    dynamic_ecd_ppg: float
    
    # Dynamic Pipe Motion (Surge / Swab)
    surge_pressure_loss_psi: float
    swab_pressure_loss_psi: float
    effective_ecd_surge_ppg: float
    effective_ecd_swab_ppg: float
    
    # Flow characteristics
    annulus_flow_regime: str  # "LAMINAR", "TURBULENT", "TRANSITIONAL"
    pipe_flow_regime: str
    bit_jet_impact_force_lbf: float
    bit_hydraulic_horsepower_hhp: float


class AnomalyClassification(str, Enum):
    NORMAL = "NORMAL"
    KICK_PRECURSOR = "KICK_PRECURSOR"
    LOSS_CIRCULATION = "LOSS_CIRCULATION"
    SWAB_INDUCED_KICK_RISK = "SWAB_INDUCED_KICK_RISK"
    SURGE_FRACTURE_RISK = "SURGE_FRACTURE_RISK"
    PACK_OFF_INCIPIENT = "PACK_OFF_INCIPIENT"
    BIT_NOZZLE_WASHOUT = "BIT_NOZZLE_WASHOUT"
    SENSOR_CALIBRATION_DRIFT = "SENSOR_CALIBRATION_DRIFT"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AnomalyDetectionResult(BaseModel):
    """Machine learning state estimation and coupled residual anomaly output."""
    timestamp: datetime
    well_id: str
    measured_depth_ft: float
    classification: AnomalyClassification
    severity: AlertSeverity
    anomaly_score: float = Field(..., ge=0.0, le=1.0, description="Anomaly confidence score [0.0 - 1.0]")
    
    # Physics-ML Residuals
    spp_residual_psi: float
    flow_residual_gpm: float
    ecd_residual_ppg: Optional[float] = None
    pit_residual_bbl_min: float = 0.0
    
    # Contextual explanation
    detection_rule: str
    diagnostic_message: str
    recommended_action: Optional[str] = None
    extra_features: Dict[str, Any] = Field(default_factory=dict)
