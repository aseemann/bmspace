"""
BMS command layer.

Each function communicates with the BMS over a transport, parses the
response, and returns a structured dataclass.  No MQTT publishing occurs
here – callers decide what to do with the data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import constants
from .protocol import (
    CAPACITY_SCALE,
    CURRENT_SCALE,
    CURRENT_SIGN_THRESHOLD,
    CURRENT_UINT16_MAX,
    TEMP_OFFSET_DECIDEGREES,
    VOLTAGE_SCALE,
    build_request,
    parse_response,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PackAnalogData:
    """Analog measurements for a single battery pack."""

    pack_number: int
    cells: list[int] = field(default_factory=list)    # mV per cell
    temps: list[float] = field(default_factory=list)  # °C per sensor
    i_pack: float = 0.0       # pack current in Amperes
    v_pack: float = 0.0       # pack voltage in Volts
    i_remain_cap: int = 0     # remaining capacity in mAh
    i_full_cap: int = 0       # full capacity in mAh
    i_design_cap: int = 0     # design capacity in mAh
    soc: float = 0.0          # state of charge in %
    soh: float = 0.0          # state of health in %
    cycles: int = 0
    cells_max_diff: int = 0   # max cell voltage spread in mV


@dataclass
class PackCapacity:
    """Overall pack capacity summary."""

    remain_cap: int    # mAh
    full_cap: int      # mAh
    design_cap: int    # mAh
    soc: float         # %
    soh: float         # %


@dataclass
class PackWarnInfo:
    """Warning and protection state for a single battery pack."""

    pack_number: int
    warnings: str
    balancing1: str           # 8-char binary string, one bit per cell
    balancing2: str
    prot_short_circuit: int
    prot_discharge_current: int
    prot_charge_current: int
    fully: int
    current_limit: int
    charge_fet: int
    discharge_fet: int
    pack_indicate: int
    reverse: int
    ac_in: int
    heart: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _exchange(transport, cid2: bytes, info: bytes = b"") -> bytes:
    """
    Send a request and return the parsed INFO bytes.

    Raises ``RuntimeError`` on protocol-level failures.
    """
    request = build_request(cid2=cid2, info=info)
    transport.send(request)
    raw = transport.receive()
    success, result = parse_response(raw)
    if not success:
        raise RuntimeError(str(result))
    return result  # type: ignore[return-value]


def _parse_flag_byte(raw_hex: bytes, table: dict[int, str]) -> tuple[int, list[str]]:
    """Decode one hex-encoded flag byte into its integer value and active flag names."""
    val = int.from_bytes(bytes.fromhex(raw_hex.decode("ascii")), "big")
    active = [table[i + 1] for i in range(8) if val & (1 << i)]
    return val, active


# ---------------------------------------------------------------------------
# Public BMS commands
# ---------------------------------------------------------------------------


def get_version(transport) -> str:
    """Return the BMS software version string."""
    info = _exchange(transport, constants.cid2SoftwareVersion)
    return bytes.fromhex(info.decode("ascii")).decode("ASCII")


def get_serial(transport) -> tuple[str, str]:
    """Return ``(bms_serial_number, pack_serial_number)``."""
    info = _exchange(transport, constants.cid2SerialNumber)
    bms_sn  = bytes.fromhex(info[0:30].decode("ascii")).decode("ASCII").replace(" ", "")
    pack_sn = bytes.fromhex(info[40:68].decode("ascii")).decode("ASCII").replace(" ", "")
    return bms_sn, pack_sn


def get_analog_data(transport, bat_number: int = 255) -> list[PackAnalogData]:
    """
    Retrieve analog measurements for all packs.

    ``bat_number=255`` requests data for all packs simultaneously.
    Returns one ``PackAnalogData`` per pack detected in the response.
    """
    battery_arg = bytes(format(bat_number, "02X"), "ASCII")
    info = _exchange(transport, constants.cid2PackAnalogData, info=battery_arg)

    byte_index = 2
    num_packs = int(info[byte_index : byte_index + 2], 16)
    byte_index += 2

    result: list[PackAnalogData] = []
    prev_cells = 0

    for p in range(1, num_packs + 1):
        pack = PackAnalogData(pack_number=p)

        num_cells = int(info[byte_index : byte_index + 2], 16)

        # Some multi-pack responses insert an extra byte between packs
        if p > 1 and num_cells != prev_cells:
            byte_index += 2
            num_cells = int(info[byte_index : byte_index + 2], 16)
            if num_cells != prev_cells:
                raise RuntimeError(
                    "Cannot parse multi-pack response: cell count mismatch"
                )
        prev_cells = num_cells
        byte_index += 2

        cell_min = cell_max = 0
        for i in range(num_cells):
            mv = int(info[byte_index : byte_index + 4], 16)
            byte_index += 4
            pack.cells.append(mv)
            if i == 0:
                cell_min = cell_max = mv
            else:
                cell_min = min(cell_min, mv)
                cell_max = max(cell_max, mv)
        pack.cells_max_diff = cell_max - cell_min

        num_temps = int(info[byte_index : byte_index + 2], 16)
        byte_index += 2
        for _ in range(num_temps):
            raw_temp = int(info[byte_index : byte_index + 4], 16)
            byte_index += 4
            pack.temps.append(round((raw_temp - TEMP_OFFSET_DECIDEGREES) / 10, 1))

        raw_current = int(info[byte_index : byte_index + 4], 16)
        byte_index += 4
        if raw_current >= CURRENT_SIGN_THRESHOLD:
            raw_current = -1 * (CURRENT_UINT16_MAX - raw_current)
        pack.i_pack = raw_current / CURRENT_SCALE

        pack.v_pack = int(info[byte_index : byte_index + 4], 16) / VOLTAGE_SCALE
        byte_index += 4

        pack.i_remain_cap = int(info[byte_index : byte_index + 4], 16) * CAPACITY_SCALE
        byte_index += 4

        byte_index += 2  # skip "P" flag byte (always 03 per protocol manual)

        pack.i_full_cap = int(info[byte_index : byte_index + 4], 16) * CAPACITY_SCALE
        byte_index += 4

        pack.soc = (
            round(pack.i_remain_cap / pack.i_full_cap * 100, 2)
            if pack.i_full_cap
            else 0.0
        )

        pack.cycles = int(info[byte_index : byte_index + 4], 16)
        byte_index += 4

        pack.i_design_cap = int(info[byte_index : byte_index + 4], 16) * CAPACITY_SCALE
        byte_index += 4

        pack.soh = (
            round(pack.i_full_cap / pack.i_design_cap * 100, 2)
            if pack.i_design_cap
            else 0.0
        )

        byte_index += 2  # reserved

        # Skip optional INFOFLAG if present (value differs from cell count)
        if (
            byte_index < len(info)
            and num_cells != int(info[byte_index : byte_index + 2], 16)
        ):
            byte_index += 2

        result.append(pack)

    return result


def get_pack_capacity(transport) -> PackCapacity:
    """Retrieve overall pack capacity data."""
    info = _exchange(transport, constants.cid2PackCapacity)

    byte_index = 0
    remain = int(info[byte_index : byte_index + 4], 16) * CAPACITY_SCALE
    byte_index += 4
    full = int(info[byte_index : byte_index + 4], 16) * CAPACITY_SCALE
    byte_index += 4
    design = int(info[byte_index : byte_index + 4], 16) * CAPACITY_SCALE

    soc = round(remain / full * 100, 2) if full else 0.0
    soh = round(full / design * 100, 2) if design else 0.0

    return PackCapacity(
        remain_cap=remain, full_cap=full, design_cap=design, soc=soc, soh=soh
    )


def get_warn_info(transport, packs: int) -> list[PackWarnInfo]:
    """
    Retrieve warning and protection states for all packs.

    ``packs`` must match the pack count from a prior ``get_analog_data``
    call so the parser can iterate the correct number of packs.
    """
    info = _exchange(transport, constants.cid2WarnInfo, info=b"FF")

    byte_index = 2
    byte_index += 2  # skip pack count echo

    result: list[PackWarnInfo] = []

    for p in range(1, packs + 1):
        warning_parts: list[str] = []

        num_cells_w = int(info[byte_index : byte_index + 2], 16)
        byte_index += 2
        for c in range(1, num_cells_w + 1):
            code = info[byte_index : byte_index + 2]
            byte_index += 2
            if code != b"00":
                state = constants.warningStates.get(code, "unknown")
                warning_parts.append(f"cell {c} {state}")

        num_temps_w = int(info[byte_index : byte_index + 2], 16)
        byte_index += 2
        for t in range(1, num_temps_w + 1):
            code = info[byte_index : byte_index + 2]
            byte_index += 2
            if code != b"00":
                state = constants.warningStates.get(code, "unknown")
                warning_parts.append(f"temp {t} {state}")

        for label in ("charge current", "total voltage", "discharge current"):
            code = info[byte_index : byte_index + 2]
            byte_index += 2
            if code != b"00":
                state = constants.warningStates.get(code, "unknown")
                warning_parts.append(f"{label} {state}")

        protect1_val, protect1_flags = _parse_flag_byte(
            info[byte_index : byte_index + 2], constants.protectState1
        )
        byte_index += 2
        if protect1_flags:
            warning_parts.append("Protection State 1: " + " | ".join(protect1_flags))

        protect2_val, protect2_flags = _parse_flag_byte(
            info[byte_index : byte_index + 2], constants.protectState2
        )
        byte_index += 2
        if protect2_flags:
            warning_parts.append("Protection State 2: " + " | ".join(protect2_flags))

        instruction_val = int.from_bytes(
            bytes.fromhex(info[byte_index : byte_index + 2].decode("ascii")), "big"
        )
        byte_index += 2

        control_val, control_flags = _parse_flag_byte(
            info[byte_index : byte_index + 2], constants.controlState
        )
        byte_index += 2
        if control_flags:
            warning_parts.append("Control State: " + " | ".join(control_flags))

        fault_val, fault_flags = _parse_flag_byte(
            info[byte_index : byte_index + 2], constants.faultState
        )
        byte_index += 2
        if fault_flags:
            warning_parts.append("Fault State: " + " | ".join(fault_flags))

        balance1 = format(int(info[byte_index : byte_index + 2], 16), "08b")
        byte_index += 2
        balance2 = format(int(info[byte_index : byte_index + 2], 16), "08b")
        byte_index += 2

        warn1_val, warn1_flags = _parse_flag_byte(
            info[byte_index : byte_index + 2], constants.warnState1
        )
        byte_index += 2
        if warn1_flags:
            warning_parts.append("Warning State 1: " + " | ".join(warn1_flags))

        warn2_val, warn2_flags = _parse_flag_byte(
            info[byte_index : byte_index + 2], constants.warnState2
        )
        byte_index += 2
        if warn2_flags:
            warning_parts.append("Warning State 2: " + " | ".join(warn2_flags))

        # Skip optional INFOFLAG
        if (
            byte_index < len(info)
            and num_cells_w != int(info[byte_index : byte_index + 2], 16)
        ):
            byte_index += 2

        result.append(
            PackWarnInfo(
                pack_number=p,
                warnings=", ".join(warning_parts),
                balancing1=balance1,
                balancing2=balance2,
                prot_short_circuit=protect1_val >> 6 & 1,
                prot_discharge_current=protect1_val >> 5 & 1,
                prot_charge_current=protect1_val >> 4 & 1,
                fully=protect2_val >> 7 & 1,
                current_limit=instruction_val >> 0 & 1,
                charge_fet=instruction_val >> 1 & 1,
                discharge_fet=instruction_val >> 2 & 1,
                pack_indicate=instruction_val >> 3 & 1,
                reverse=instruction_val >> 4 & 1,
                ac_in=instruction_val >> 5 & 1,
                heart=instruction_val >> 7 & 1,
            )
        )

    return result
