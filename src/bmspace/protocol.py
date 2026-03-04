"""
Pure protocol functions for the PACE BMS RS232 protocol.

No I/O, no globals – fully unit-testable.

Packet structure:
  SOI | VER | ADR | CID1 | CID2 | LCHKSUM | LENID | INFO | CHKSUM | EOI
  ~     25    01    46     xx     x         xxx     ...    xxxx     \r

All fields are ASCII hex encoded bytes except SOI (0x7E) and EOI (0x0D).
"""
from __future__ import annotations

# Protocol framing
SOI: bytes = b"\x7e"   # Start of information (ASCII '~')
EOI: bytes = b"\x0d"   # End of information (ASCII '\r')

# Default protocol header fields
DEFAULT_VER: bytes  = b"\x32\x35"   # "25"
DEFAULT_ADR: bytes  = b"\x30\x31"   # "01"
DEFAULT_CID1: bytes = b"\x34\x36"   # "46"

# Physical unit scaling constants
CURRENT_SIGN_THRESHOLD: int = 32768   # values >= this are negative (two's complement)
CURRENT_UINT16_MAX: int     = 65535
TEMP_OFFSET_DECIDEGREES: int = 2730  # 273.0 K × 10
CURRENT_SCALE: int           = 100   # raw / 100 → Amperes
VOLTAGE_SCALE: int           = 1000  # raw / 1000 → Volts
CAPACITY_SCALE: int          = 10    # raw × 10 → mAh


def chksum_calc(data: bytes) -> str:
    """
    Calculate the 16-bit packet checksum.

    Algorithm: sum all bytes from index 1 onwards, modulo 65536,
    flip all bits, add 1, return as uppercase hex string.
    """
    total = sum(data[1:]) % 65536
    bits = format(total, "016b")
    flipped = bits.translate(str.maketrans("01", "10"))
    result = int(flipped, 2) + 1
    return format(result, "X")


def lchksum_calc(lenid: bytes) -> str:
    """
    Calculate the 4-bit length checksum over 3 ASCII hex nibbles.

    Algorithm: interpret each ASCII hex character as a nibble, sum them,
    modulo 16, flip 4 bits, add 1 (wraps to 0 if result > 15),
    return as uppercase hex character.
    """
    total = sum(int(chr(b), 16) for b in lenid) % 16
    bits = format(total, "04b")
    flipped = bits.translate(str.maketrans("01", "10"))
    result = int(flipped, 2) + 1
    if result > 15:
        result = 0
    return format(result, "X")


def cid2_return_code(rtn: bytes) -> tuple[bool, str | None]:
    """
    Interpret a BMS RTN response code.

    Returns ``(is_error, message)``.
    ``is_error=False`` means success; the message is ``None`` in that case.
    Unknown codes are treated as success (pass-through).
    """
    _codes: dict[bytes, tuple[bool, str | None]] = {
        b"00": (False, None),
        b"01": (True, "RTN Error 01: Undefined RTN error"),
        b"02": (True, "RTN Error 02: CHKSUM error"),
        b"03": (True, "RTN Error 03: LCHKSUM error"),
        b"04": (True, "RTN Error 04: CID2 undefined"),
        b"05": (True, "RTN Error 05: Undefined error"),
        b"06": (True, "RTN Error 06: Undefined error"),
        b"09": (True, "RTN Error 09: Operation or write error"),
    }
    return _codes.get(rtn, (False, None))


def build_request(
    cid2: bytes,
    info: bytes = b"",
    ver: bytes = DEFAULT_VER,
    adr: bytes = DEFAULT_ADR,
    cid1: bytes = DEFAULT_CID1,
) -> bytes:
    """
    Build a complete BMS protocol request packet.

    Returns the full packet as bytes including SOI and EOI.
    """
    lenid_int = len(info)
    lenid = bytes(format(lenid_int, "03X"), "ASCII")

    if lenid == b"000":
        lchksum = b"0"
    else:
        lchksum = bytes(lchksum_calc(lenid), "ASCII")

    packet = SOI + ver + adr + cid1 + cid2 + lchksum + lenid + info
    chksum = bytes(chksum_calc(packet), "ASCII")
    return packet + chksum + EOI


def parse_response(data: bytes) -> tuple[bool, bytes | str]:
    """
    Parse an incoming BMS response packet.

    Returns ``(True, INFO_bytes)`` on success or ``(False, error_message)``
    on any validation failure.
    """
    if not data or data[0:1] != SOI:
        return False, "Incorrect starting byte for incoming data"

    if len(data) < 14:
        return False, f"Response too short: {len(data)} bytes"

    rtn = data[7:9]
    is_error, msg = cid2_return_code(rtn)
    if is_error:
        return False, msg  # type: ignore[return-value]

    raw_lenid = data[10:13]
    try:
        lenid = int(raw_lenid, 16)
    except ValueError:
        return False, f"Cannot parse LENID: {raw_lenid!r}"

    lchksum_received = data[9]
    calc_lchksum = lchksum_calc(raw_lenid)
    if lchksum_received != ord(calc_lchksum):
        return False, (
            f"LCHKSUM received: {lchksum_received} "
            f"does not match calculated: {ord(calc_lchksum)}"
        )

    info = data[13 : 13 + lenid]
    chksum_received = data[13 + lenid : 13 + lenid + 4]
    calc_chksum = chksum_calc(data[: len(data) - 5])

    try:
        received_str = chksum_received.decode("ASCII")
    except (UnicodeDecodeError, AttributeError):
        return False, "Cannot decode CHKSUM bytes"

    if received_str != calc_chksum:
        return False, (
            f"Checksum mismatch: received {received_str!r}, "
            f"calculated {calc_chksum!r}"
        )

    return True, info
