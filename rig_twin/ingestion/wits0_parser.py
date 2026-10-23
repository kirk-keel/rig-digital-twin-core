"""WITS Level 0 (WITS0) rigsite streaming protocol parser and TCP server.

Parses standard ASCII WITS records (Record 01 General Drilling, Record 08 Survey, Record 12 Mud)
broadcast by rig instrumentation units (Pason, NOV/Totco, SLB, Baker Hughes).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Callable, Dict, List, Optional
from rig_twin.core.models import TelemetryRecord

logger = logging.getLogger("rig_twin.wits0")


class Wits0Parser:
    """Encodes and decodes WITS Level 0 ASCII packets."""

    ITEM_MAP = {
        # Record 01: General Drilling
        "0108": "bit_depth_ft",
        "0109": "hole_depth_ft",
        "0110": "standpipe_pressure_psi",
        "0112": "flow_rate_in_gpm",
        "0113": "flow_rate_out_gpm",
        "0114": "surface_rpm",
        "0115": "surface_torque_ft_lbf",
        "0116": "hook_load_klbf",
        "0117": "weight_on_bit_klbf",
        "0118": "rate_of_penetration_ft_hr",
        # Record 12: Mud & Hydraulics
        "1208": "mud_weight_in_ppg",
        "1209": "mud_weight_out_ppg",
        "1210": "pit_volume_total_bbl",
        "1212": "pit_gain_loss_bbl",
        "1213": "downhole_annular_pressure_psi",
        "1214": "downhole_ecd_ppg",
    }

    @classmethod
    def parse_packet(cls, packet_str: str, well_id: str = "RIG-WITS0-01") -> Optional[TelemetryRecord]:
        """Parse a single WITS0 packet delimited by '&&' and '!!'."""
        lines = [line.strip() for line in packet_str.splitlines() if line.strip()]
        if not lines:
            return None

        # Verify delimiter boundaries if present
        raw_values: Dict[str, float] = {}

        for line in lines:
            if line in ("&&", "!!"):
                continue
            if len(line) >= 4:
                code = line[:4]
                val_str = line[4:].strip()
                try:
                    raw_values[code] = float(val_str)
                except ValueError:
                    continue

        if not raw_values:
            return None

        bit_d = raw_values.get("0108", 0.0)
        hole_d = raw_values.get("0109", bit_d)
        spp = raw_values.get("0110", 0.0)
        flow_in = raw_values.get("0112", 0.0)
        flow_out = raw_values.get("0113", flow_in)
        rpm = raw_values.get("0114", 0.0)
        torque = raw_values.get("0115", 0.0)
        hkld = raw_values.get("0116", 0.0)

        mw_in = raw_values.get("1208", 10.0)
        mw_out = raw_values.get("1209", mw_in)
        pit_vol = raw_values.get("1210", 500.0)
        pwd_ap = raw_values.get("1213", None)
        pwd_ecd = raw_values.get("1214", None)

        return TelemetryRecord(
            timestamp=datetime.now(timezone.utc),
            well_id=well_id,
            measured_depth_ft=hole_d,
            true_vertical_depth_ft=hole_d,
            bit_depth_ft=bit_d,
            hole_depth_ft=hole_d,
            flow_rate_in_gpm=flow_in,
            flow_rate_out_gpm=flow_out,
            standpipe_pressure_psi=spp,
            downhole_annular_pressure_psi=pwd_ap,
            downhole_ecd_ppg=pwd_ecd,
            hook_load_klbf=hkld,
            surface_rpm=rpm,
            surface_torque_ft_lbf=torque,
            mud_weight_in_ppg=mw_in,
            mud_weight_out_ppg=mw_out,
            pit_volume_total_bbl=pit_vol,
        )

    @classmethod
    def format_packet(cls, telemetry: TelemetryRecord) -> str:
        """Format a TelemetryRecord into standard WITS Level 0 packet string."""
        lines = [
            "&&",
            f"0108{telemetry.bit_depth_ft:.2f}",
            f"0109{telemetry.hole_depth_ft:.2f}",
            f"0110{telemetry.standpipe_pressure_psi:.1f}",
            f"0112{telemetry.flow_rate_in_gpm:.1f}",
            f"0113{telemetry.flow_rate_out_gpm:.1f}",
            f"0114{telemetry.surface_rpm:.1f}",
            f"0115{telemetry.surface_torque_ft_lbf:.1f}",
            f"0116{telemetry.hook_load_klbf:.1f}",
            f"1208{telemetry.mud_weight_in_ppg:.2f}",
            f"1209{telemetry.mud_weight_out_ppg:.2f}",
            f"1210{telemetry.pit_volume_total_bbl:.2f}",
            "!!",
        ]
        return "\r\n".join(lines) + "\r\n"


class Wits0TcpServer:
    """Asynchronous TCP socket server ingesting live WITS0 ASCII stream connections."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        record_callback: Optional[Callable[[TelemetryRecord], None]] = None,
        well_id: str = "WELL-WITS0",
    ):
        self.host = host
        self.port = port
        self.record_callback = record_callback
        self.well_id = well_id
        self.server: Optional[asyncio.Server] = None
        self.is_running = False

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        buffer = ""
        while self.is_running:
            try:
                data = await reader.read(1024)
                if not data:
                    break
                buffer += data.decode("ascii", errors="ignore")
                while "&&" in buffer and "!!" in buffer:
                    start_idx = buffer.index("&&")
                    end_idx = buffer.index("!!", start_idx) + 2
                    packet = buffer[start_idx:end_idx]
                    buffer = buffer[end_idx:]

                    record = Wits0Parser.parse_packet(packet, well_id=self.well_id)
                    if record and self.record_callback:
                        self.record_callback(record)
            except Exception as e:
                logger.error(f"Error handling WITS0 client: {e}")
                break
        writer.close()
        await writer.wait_closed()

    async def start(self) -> None:
        """Start listening for incoming TCP WITS0 stream connections."""
        self.is_running = True
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)

    async def stop(self) -> None:
        """Stop the TCP server."""
        self.is_running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
