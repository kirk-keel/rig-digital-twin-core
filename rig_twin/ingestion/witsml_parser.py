"""WITSML stream and batch parser for real-time rig telemetry ingestion.

Supports both WITSML 1.3.1 / 1.4.1 XML payloads and modern JSON-WITSML streams.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, Iterator, List, Optional
import xml.etree.ElementTree as ET
from rig_twin.core.models import TelemetryRecord


class WitsmlFieldMapping:
    """Flexible mnemonic aliases commonly encountered in drilling data aggregators."""
    
    TIMESTAMP = ["timestamp", "dTim", "time", "dateTime", "DTIM"]
    MD = ["measured_depth_ft", "md", "depth", "dmea", "MD", "dept"]
    TVD = ["true_vertical_depth_ft", "tvd", "dver", "TVD", "tvdp"]
    BIT_DEPTH = ["bit_depth_ft", "bit_depth", "dbim", "bdep", "BDEP", "bdepth"]
    HOLE_DEPTH = ["hole_depth_ft", "hole_depth", "dhole", "dh", "DMEA_HOLE"]
    STRING_VELOCITY = ["string_velocity_ft_min", "string_velocity", "v_str", "rov", "vels", "VSTR"]
    FLOW_IN = ["flow_rate_in_gpm", "flow_in", "flowin", "flwi", "FLWI", "gpm_in"]
    FLOW_OUT = ["flow_rate_out_gpm", "flow_out", "flowout", "flwo", "FLWO", "gpm_out"]
    SPP = ["standpipe_pressure_psi", "spp", "pump_press", "prss", "SPP", "pumppress"]
    DOWNHOLE_AP = ["downhole_annular_pressure_psi", "pwd_ap", "aprs", "ann_press", "PWD_AP"]
    DOWNHOLE_ECD = ["downhole_ecd_ppg", "pwd_ecd", "ecd", "downhole_ecd", "PWD_ECD"]
    HOOK_LOAD = ["hook_load_klbf", "hook_load", "hkld", "HKLD", "hookload"]
    RPM = ["surface_rpm", "rpm", "rpm_surf", "SURF_RPM"]
    TORQUE = ["surface_torque_ft_lbf", "torque", "torq", "TORQ", "surf_torq"]
    MUD_WEIGHT_IN = ["mud_weight_in_ppg", "mwin", "mud_weight_in", "denv_in", "MWIN"]
    MUD_WEIGHT_OUT = ["mud_weight_out_ppg", "mwout", "mud_weight_out", "denv_out", "MWOUT"]
    PIT_VOLUME = ["pit_volume_total_bbl", "pit_vol", "pvt", "volm", "PVT", "pit_volume"]
    PIT_ROC = ["pit_rate_of_change_bbl_hr", "pit_gain_loss", "pit_roc", "ROC_PIT"]


class WitsmlParser:
    """Parses WITSML XML or JSON formatted streams into normalized TelemetryRecords."""

    @staticmethod
    def _parse_timestamp(val: Any) -> datetime:
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(val, str):
            # Try ISO parse
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        return datetime.now(timezone.utc)

    @classmethod
    def _extract_field(cls, record: Dict[str, Any], aliases: List[str], default: Any = 0.0) -> Any:
        for alias in aliases:
            if alias in record and record[alias] is not None:
                try:
                    val = record[alias]
                    if default is None and val == "":
                        return None
                    return float(val) if isinstance(default, float) else val
                except (ValueError, TypeError):
                    continue
        return default

    @classmethod
    def parse_dict(cls, data: Dict[str, Any], well_id: str = "WELL-01") -> TelemetryRecord:
        """Parse a single flattened dictionary / JSON object into TelemetryRecord."""
        ts = cls._parse_timestamp(cls._extract_field(data, WitsmlFieldMapping.TIMESTAMP, default=""))
        
        md = float(cls._extract_field(data, WitsmlFieldMapping.MD, 0.0))
        tvd = float(cls._extract_field(data, WitsmlFieldMapping.TVD, md))
        bit_d = float(cls._extract_field(data, WitsmlFieldMapping.BIT_DEPTH, md))
        hole_d = float(cls._extract_field(data, WitsmlFieldMapping.HOLE_DEPTH, md))

        string_vel = float(cls._extract_field(data, WitsmlFieldMapping.STRING_VELOCITY, 0.0))
        flow_in = float(cls._extract_field(data, WitsmlFieldMapping.FLOW_IN, 0.0))
        flow_out = float(cls._extract_field(data, WitsmlFieldMapping.FLOW_OUT, flow_in))
        spp = float(cls._extract_field(data, WitsmlFieldMapping.SPP, 0.0))

        pwd_ap = cls._extract_field(data, WitsmlFieldMapping.DOWNHOLE_AP, None)
        pwd_ecd = cls._extract_field(data, WitsmlFieldMapping.DOWNHOLE_ECD, None)

        hkld = float(cls._extract_field(data, WitsmlFieldMapping.HOOK_LOAD, 0.0))
        rpm = float(cls._extract_field(data, WitsmlFieldMapping.RPM, 0.0))
        torq = float(cls._extract_field(data, WitsmlFieldMapping.TORQUE, 0.0))

        mw_in = float(cls._extract_field(data, WitsmlFieldMapping.MUD_WEIGHT_IN, 10.0))
        mw_out = float(cls._extract_field(data, WitsmlFieldMapping.MUD_WEIGHT_OUT, mw_in))
        pit_vol = float(cls._extract_field(data, WitsmlFieldMapping.PIT_VOLUME, 500.0))
        pit_roc = float(cls._extract_field(data, WitsmlFieldMapping.PIT_ROC, 0.0))

        w_id = str(data.get("well_id", well_id))

        return TelemetryRecord(
            timestamp=ts,
            well_id=w_id,
            measured_depth_ft=md,
            true_vertical_depth_ft=tvd,
            bit_depth_ft=bit_d,
            hole_depth_ft=hole_d,
            string_velocity_ft_min=string_vel,
            flow_rate_in_gpm=flow_in,
            flow_rate_out_gpm=flow_out,
            standpipe_pressure_psi=spp,
            downhole_annular_pressure_psi=float(pwd_ap) if pwd_ap is not None else None,
            downhole_ecd_ppg=float(pwd_ecd) if pwd_ecd is not None else None,
            hook_load_klbf=hkld,
            surface_rpm=rpm,
            surface_torque_ft_lbf=torq,
            mud_weight_in_ppg=mw_in,
            mud_weight_out_ppg=mw_out,
            pit_volume_total_bbl=pit_vol,
            pit_rate_of_change_bbl_hr=pit_roc,
        )

    @classmethod
    def parse_batch_json(cls, json_payload: str, default_well_id: str = "WELL-01") -> List[TelemetryRecord]:
        """Parse JSON array of WITSML data points."""
        raw_items = json.loads(json_payload)
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        return [cls.parse_dict(item, default_well_id) for item in raw_items]

    @classmethod
    def parse_witsml_xml(cls, xml_text: str, default_well_id: str = "WELL-01") -> List[TelemetryRecord]:
        """Parse WITSML 1.3.1 / 1.4.1 log curve XML message."""
        root = ET.fromstring(xml_text)
        
        # Remove namespace prefixes if present
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        # Extract well identifier
        well_elem = root.find(".//nameWell")
        well_id = well_elem.text if well_elem is not None and well_elem.text else default_well_id

        # Extract mnemonic headers
        mnemonic_elements = root.findall(".//logCurveInfo/mnemonic")
        mnemonics = [m.text.strip() for m in mnemonic_elements if m.text]

        records: List[TelemetryRecord] = []
        data_nodes = root.findall(".//logData/data")
        
        for d_node in data_nodes:
            if not d_node.text:
                continue
            line = d_node.text.strip()
            parts = [p.strip() for p in line.split(",")]
            
            if mnemonics and len(parts) == len(mnemonics):
                row_dict = dict(zip(mnemonics, parts))
            else:
                # Default positional fallback: TIME, MD, TVD, BDEP, FLWI, FLWO, SPP, HKLD, RPM, TORQ, MWIN, PVT
                fields = ["DTIM", "MD", "TVD", "BDEP", "FLWI", "FLWO", "SPP", "HKLD", "RPM", "TORQ", "MWIN", "PVT"]
                row_dict = dict(zip(fields[: len(parts)], parts))
                
            records.append(cls.parse_dict(row_dict, well_id=well_id))

        return records
