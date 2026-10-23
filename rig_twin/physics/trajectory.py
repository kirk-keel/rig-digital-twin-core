"""3D Wellbore directional trajectory engine using the Minimum Curvature Method (MCM).

Standard API/SPE directional surveying algorithm to compute true 3D spatial coordinates
(TVD, Northing, Easting, Dogleg Severity) from directional station surveys.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


class SurveyStation(BaseModel):
    """Directional survey station measuring depth, inclination, and azimuth."""
    measured_depth_ft: float
    inclination_deg: float
    azimuth_deg: float  # Grid or true north azimuth (0 - 360)


class TrajectoryPoint(BaseModel):
    """Calculated 3D spatial wellbore trajectory coordinate point."""
    measured_depth_ft: float
    inclination_deg: float
    azimuth_deg: float
    true_vertical_depth_ft: float
    northing_ft: float
    easting_ft: float
    dogleg_severity_deg_100ft: float
    closure_distance_ft: float
    closure_azimuth_deg: float
    vertical_section_ft: float


class DirectionalTrajectoryEngine:
    """Calculates 3D wellbore trajectory using the Minimum Curvature Method (API standard)."""

    def __init__(self, vertical_section_azimuth_deg: float = 45.0):
        self.vs_azimuth_rad = math.radians(vertical_section_azimuth_deg)

    @staticmethod
    def minimum_curvature_step(
        s1: SurveyStation, s2: SurveyStation
    ) -> Tuple[float, float, float, float]:
        """Compute delta TVD, North, East, and Dogleg Severity between two survey stations.
        
        Returns:
            (delta_tvd_ft, delta_north_ft, delta_east_ft, dls_deg_per_100ft)
        """
        delta_md = s2.measured_depth_ft - s1.measured_depth_ft
        if delta_md <= 0.0:
            return 0.0, 0.0, 0.0, 0.0

        i1 = math.radians(s1.inclination_deg)
        i2 = math.radians(s2.inclination_deg)
        a1 = math.radians(s1.azimuth_deg)
        a2 = math.radians(s2.azimuth_deg)

        # Dogleg angle beta: cos(beta) = cos(I1)*cos(I2) + sin(I1)*sin(I2)*cos(A2 - A1)
        cos_beta = math.cos(i1) * math.cos(i2) + math.sin(i1) * math.sin(i2) * math.cos(a2 - a1)
        cos_beta = max(min(cos_beta, 1.0), -1.0)
        beta = math.acos(cos_beta)

        # Ratio factor RF = (2 / beta) * tan(beta / 2) (limit beta -> 0 is 1.0)
        if abs(beta) < 1e-6:
            rf = 1.0
        else:
            rf = (2.0 / beta) * math.tan(beta / 2.0)

        # Coordinates incremental integration
        delta_north = (delta_md / 2.0) * (math.sin(i1) * math.cos(a1) + math.sin(i2) * math.cos(a2)) * rf
        delta_east = (delta_md / 2.0) * (math.sin(i1) * math.sin(a1) + math.sin(i2) * math.sin(a2)) * rf
        delta_tvd = (delta_md / 2.0) * (math.cos(i1) + math.cos(i2)) * rf

        # Dogleg severity in degrees per 100 ft
        dls = (math.degrees(beta) / delta_md) * 100.0

        return delta_tvd, delta_north, delta_east, dls

    def compute_trajectory(self, stations: List[SurveyStation]) -> List[TrajectoryPoint]:
        """Calculate complete 3D trajectory from a list of survey stations."""
        if not stations:
            return []

        sorted_stations = sorted(stations, key=lambda s: s.measured_depth_ft)
        points: List[TrajectoryPoint] = []

        # Origin tie-in point (surface)
        first = sorted_stations[0]
        if first.measured_depth_ft > 0.0:
            # Insert ground/rotary table origin
            sorted_stations.insert(0, SurveyStation(measured_depth_ft=0.0, inclination_deg=0.0, azimuth_deg=first.azimuth_deg))

        tvd = 0.0
        north = 0.0
        east = 0.0

        for i in range(len(sorted_stations)):
            if i == 0:
                p = TrajectoryPoint(
                    measured_depth_ft=sorted_stations[0].measured_depth_ft,
                    inclination_deg=sorted_stations[0].inclination_deg,
                    azimuth_deg=sorted_stations[0].azimuth_deg,
                    true_vertical_depth_ft=0.0,
                    northing_ft=0.0,
                    easting_ft=0.0,
                    dogleg_severity_deg_100ft=0.0,
                    closure_distance_ft=0.0,
                    closure_azimuth_deg=0.0,
                    vertical_section_ft=0.0,
                )
                points.append(p)
                continue

            s_prev = sorted_stations[i - 1]
            s_curr = sorted_stations[i]

            d_tvd, d_north, d_east, dls = self.minimum_curvature_step(s_prev, s_curr)
            tvd += d_tvd
            north += d_north
            east += d_east

            closure_dist = math.sqrt(north ** 2 + east ** 2)
            closure_azi_deg = (math.degrees(math.atan2(east, north)) + 360.0) % 360.0
            vert_section = closure_dist * math.cos(math.radians(closure_azi_deg) - self.vs_azimuth_rad)

            p = TrajectoryPoint(
                measured_depth_ft=round(s_curr.measured_depth_ft, 2),
                inclination_deg=round(s_curr.inclination_deg, 2),
                azimuth_deg=round(s_curr.azimuth_deg, 2),
                true_vertical_depth_ft=round(tvd, 2),
                northing_ft=round(north, 2),
                easting_ft=round(east, 2),
                dogleg_severity_deg_100ft=round(dls, 2),
                closure_distance_ft=round(closure_dist, 2),
                closure_azimuth_deg=round(closure_azi_deg, 2),
                vertical_section_ft=round(vert_section, 2),
            )
            points.append(p)

        return points

    def interpolate_position(
        self, trajectory: List[TrajectoryPoint], target_md_ft: float
    ) -> TrajectoryPoint:
        """Interpolate 3D position at an arbitrary measured depth along the trajectory."""
        if not trajectory:
            return TrajectoryPoint(
                measured_depth_ft=target_md_ft,
                inclination_deg=0.0,
                azimuth_deg=0.0,
                true_vertical_depth_ft=target_md_ft,
                northing_ft=0.0,
                easting_ft=0.0,
                dogleg_severity_deg_100ft=0.0,
                closure_distance_ft=0.0,
                closure_azimuth_deg=0.0,
                vertical_section_ft=0.0,
            )

        if target_md_ft <= trajectory[0].measured_depth_ft:
            return trajectory[0]
        if target_md_ft >= trajectory[-1].measured_depth_ft:
            # Extrapolate tangent from last point
            last = trajectory[-1]
            delta_md = target_md_ft - last.measured_depth_ft
            inc_rad = math.radians(last.inclination_deg)
            azi_rad = math.radians(last.azimuth_deg)

            d_tvd = delta_md * math.cos(inc_rad)
            d_north = delta_md * math.sin(inc_rad) * math.cos(azi_rad)
            d_east = delta_md * math.sin(inc_rad) * math.sin(azi_rad)

            new_north = last.northing_ft + d_north
            new_east = last.easting_ft + d_east
            closure = math.sqrt(new_north ** 2 + new_east ** 2)
            azi_closure = (math.degrees(math.atan2(new_east, new_north)) + 360.0) % 360.0

            return TrajectoryPoint(
                measured_depth_ft=round(target_md_ft, 2),
                inclination_deg=last.inclination_deg,
                azimuth_deg=last.azimuth_deg,
                true_vertical_depth_ft=round(last.true_vertical_depth_ft + d_tvd, 2),
                northing_ft=round(new_north, 2),
                easting_ft=round(new_east, 2),
                dogleg_severity_deg_100ft=0.0,
                closure_distance_ft=round(closure, 2),
                closure_azimuth_deg=round(azi_closure, 2),
                vertical_section_ft=round(closure * math.cos(math.radians(azi_closure) - self.vs_azimuth_rad), 2),
            )

        # Binary search interval
        low = 0
        high = len(trajectory) - 1
        while low <= high:
            mid = (low + high) // 2
            if trajectory[mid].measured_depth_ft <= target_md_ft <= trajectory[mid + 1].measured_depth_ft:
                p1 = trajectory[mid]
                p2 = trajectory[mid + 1]
                s1 = SurveyStation(measured_depth_ft=p1.measured_depth_ft, inclination_deg=p1.inclination_deg, azimuth_deg=p1.azimuth_deg)
                s_target = SurveyStation(measured_depth_ft=target_md_ft, inclination_deg=p1.inclination_deg + (p2.inclination_deg - p1.inclination_deg) * ((target_md_ft - p1.measured_depth_ft) / max(p2.measured_depth_ft - p1.measured_depth_ft, 0.01)), azimuth_deg=p1.azimuth_deg + (p2.azimuth_deg - p1.azimuth_deg) * ((target_md_ft - p1.measured_depth_ft) / max(p2.measured_depth_ft - p1.measured_depth_ft, 0.01)))
                d_tvd, d_north, d_east, dls = self.minimum_curvature_step(s1, s_target)
                north = p1.northing_ft + d_north
                east = p1.easting_ft + d_east
                closure = math.sqrt(north ** 2 + east ** 2)
                azi_closure = (math.degrees(math.atan2(east, north)) + 360.0) % 360.0
                return TrajectoryPoint(
                    measured_depth_ft=round(target_md_ft, 2),
                    inclination_deg=round(s_target.inclination_deg, 2),
                    azimuth_deg=round(s_target.azimuth_deg, 2),
                    true_vertical_depth_ft=round(p1.true_vertical_depth_ft + d_tvd, 2),
                    northing_ft=round(north, 2),
                    easting_ft=round(east, 2),
                    dogleg_severity_deg_100ft=round(dls, 2),
                    closure_distance_ft=round(closure, 2),
                    closure_azimuth_deg=round(azi_closure, 2),
                    vertical_section_ft=round(closure * math.cos(math.radians(azi_closure) - self.vs_azimuth_rad), 2),
                )
            elif trajectory[mid].measured_depth_ft < target_md_ft:
                low = mid + 1
            else:
                high = mid - 1

        return trajectory[-1]
