"""Unit tests for WITSML streaming telemetry parsing (JSON & XML formats)."""

import json
from datetime import datetime, timezone
import pytest
from rig_twin.ingestion.witsml_parser import WitsmlParser


def test_parse_dict_standard():
    payload = {
        "timestamp": "2026-10-23T12:00:00Z",
        "well_id": "OFFSHORE-01",
        "measured_depth_ft": 10500.0,
        "true_vertical_depth_ft": 9800.0,
        "bit_depth_ft": 10500.0,
        "hole_depth_ft": 10500.0,
        "flow_rate_in_gpm": 550.0,
        "flow_rate_out_gpm": 552.0,
        "standpipe_pressure_psi": 2850.0,
        "surface_rpm": 110.0,
        "surface_torque_ft_lbf": 9200.0,
        "mud_weight_in_ppg": 11.2,
        "pit_volume_total_bbl": 520.0,
    }

    record = WitsmlParser.parse_dict(payload)
    assert record.well_id == "OFFSHORE-01"
    assert record.measured_depth_ft == 10500.0
    assert record.flow_rate_in_gpm == 550.0
    assert record.delta_flow_gpm == 2.0


def test_parse_dict_with_witsml_mnemonics():
    # Real-world WITSML log mnemonic names
    payload = {
        "DTIM": "2026-10-23T12:05:00+00:00",
        "MD": 11020.5,
        "TVD": 10200.0,
        "BDEP": 11020.5,
        "FLWI": 600.0,
        "FLWO": 600.0,
        "SPP": 3100.0,
        "HKLD": 220.0,
        "TORQ": 8500.0,
        "MWIN": 12.1,
        "PVT": 540.0,
    }

    record = WitsmlParser.parse_dict(payload, well_id="RIG-BRAVO")
    assert record.well_id == "RIG-BRAVO"
    assert record.measured_depth_ft == 11020.5
    assert record.standpipe_pressure_psi == 3100.0
    assert record.mud_weight_in_ppg == 12.1


def test_parse_batch_json():
    items = [
        {"timestamp": "2026-10-23T12:00:00Z", "measured_depth_ft": 1000.0, "flow_rate_in_gpm": 400.0},
        {"timestamp": "2026-10-23T12:00:05Z", "measured_depth_ft": 1001.0, "flow_rate_in_gpm": 400.0},
    ]
    records = WitsmlParser.parse_batch_json(json.dumps(items), default_well_id="WELL-ALPHA")
    assert len(records) == 2
    assert records[0].well_id == "WELL-ALPHA"
    assert records[1].measured_depth_ft == 1001.0


def test_parse_witsml_xml():
    xml_data = """<?xml version="1.0" encoding="UTF-8"?>
    <logs xmlns="http://www.witsml.org/schemas/1series" version="1.4.1.1">
      <log uidWell="W-01" uidWellbore="WB-01" uid="LOG-01">
        <nameWell>DEEPWATER-EXPLORER-1</nameWell>
        <logCurveInfo uid="c1"><mnemonic>DTIM</mnemonic></logCurveInfo>
        <logCurveInfo uid="c2"><mnemonic>MD</mnemonic></logCurveInfo>
        <logCurveInfo uid="c3"><mnemonic>TVD</mnemonic></logCurveInfo>
        <logCurveInfo uid="c4"><mnemonic>BDEP</mnemonic></logCurveInfo>
        <logCurveInfo uid="c5"><mnemonic>FLWI</mnemonic></logCurveInfo>
        <logCurveInfo uid="c6"><mnemonic>FLWO</mnemonic></logCurveInfo>
        <logCurveInfo uid="c7"><mnemonic>SPP</mnemonic></logCurveInfo>
        <logData>
          <data>2026-10-23T12:00:00Z, 8500.0, 7500.0, 8500.0, 480.0, 480.0, 2450.0</data>
          <data>2026-10-23T12:00:05Z, 8500.5, 7500.5, 8500.5, 480.0, 495.0, 2445.0</data>
        </logData>
      </log>
    </logs>
    """
    records = WitsmlParser.parse_witsml_xml(xml_data)
    assert len(records) == 2
    assert records[0].well_id == "DEEPWATER-EXPLORER-1"
    assert records[0].measured_depth_ft == 8500.0
    assert records[0].flow_rate_in_gpm == 480.0
    assert records[1].flow_rate_out_gpm == 495.0
