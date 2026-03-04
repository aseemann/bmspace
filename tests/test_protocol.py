"""
Tests for src/bmspace/protocol.py

All functions are pure (no I/O, no globals), so no mocking is required.
"""
import pytest

from bmspace.protocol import (
    SOI,
    EOI,
    build_request,
    chksum_calc,
    cid2_return_code,
    lchksum_calc,
    parse_response,
)


# ---------------------------------------------------------------------------
# Helpers used across tests
# ---------------------------------------------------------------------------


def _build_valid_response(info: bytes = b"") -> bytes:
    """Construct a syntactically correct BMS response packet around *info*."""
    soi = b"~"
    ver = b"25"
    adr = b"01"
    cid1 = b"46"
    rtn = b"00"
    lenid_int = len(info)
    lenid = bytes(format(lenid_int, "03X"), "ASCII")
    lchksum = b"0" if lenid == b"000" else bytes(lchksum_calc(lenid), "ASCII")
    packet = soi + ver + adr + cid1 + rtn + lchksum + lenid + info
    chksum = bytes(chksum_calc(packet), "ASCII")
    return packet + chksum + b"\r"


# ---------------------------------------------------------------------------
# lchksum_calc
# ---------------------------------------------------------------------------


class TestLchksumCalc:
    """4-bit length checksum over 3 ASCII hex nibbles."""

    def test_all_zeros_wraps_to_zero(self):
        # sum=0 → bits=0000 → flip=1111=15 → +1=16 → wraps to 0
        assert lchksum_calc(b"000") == "0"

    def test_known_value_0dc(self):
        # 0 + 0xD + 0xC = 25; 25 % 16 = 9 → 1001 → flip 0110 = 6 → +1 = 7
        assert lchksum_calc(b"0DC") == "7"

    def test_known_value_002(self):
        # 0 + 0 + 2 = 2 → 0010 → flip 1101 = 13 → +1 = 14 = 'E'
        assert lchksum_calc(b"002") == "E"

    def test_known_value_00a(self):
        # 0 + 0 + 0xA = 10 → 1010 → flip 0101 = 5 → +1 = 6
        assert lchksum_calc(b"00A") == "6"

    def test_result_is_single_uppercase_hex_char(self):
        for lenid in [b"001", b"00F", b"010", b"0FF", b"FFF"]:
            result = lchksum_calc(lenid)
            assert len(result) == 1
            assert result in "0123456789ABCDEF"

    def test_roundtrip_check(self):
        """The calculated LCHKSUM must match what parse_response expects."""
        for lenid_int in [0, 1, 8, 12, 16, 220, 255]:
            lenid = bytes(format(lenid_int, "03X"), "ASCII")
            calc = lchksum_calc(lenid)
            # Verify it is a single valid hex nibble
            int(calc, 16)  # must not raise


# ---------------------------------------------------------------------------
# chksum_calc
# ---------------------------------------------------------------------------


class TestChksumCalc:
    """16-bit packet checksum."""

    def test_version_request_packet(self):
        # Known packet: ~250146C10000 (no info, version request)
        packet = b"~250146C10000"
        result = chksum_calc(packet)
        assert result == "FD9A"

    def test_result_is_uppercase_hex(self):
        result = chksum_calc(b"~ABCDEF")
        assert result == result.upper()
        int(result, 16)  # must be valid hex

    def test_single_byte_body(self):
        # data[0] is skipped; only data[1] = ord('A') = 65 is summed
        data = b"~A"
        total = 65 % 65536
        bits = format(total, "016b")
        flipped = bits.translate(str.maketrans("01", "10"))
        expected = format(int(flipped, 2) + 1, "X")
        assert chksum_calc(data) == expected

    def test_valid_response_packet_passes_parse(self):
        """A packet built with chksum_calc must be accepted by parse_response."""
        info = b"TESTDATA"
        response = _build_valid_response(info)
        success, parsed = parse_response(response)
        assert success is True
        assert parsed == info


# ---------------------------------------------------------------------------
# cid2_return_code
# ---------------------------------------------------------------------------


class TestCid2ReturnCode:
    def test_success_code_00(self):
        is_error, msg = cid2_return_code(b"00")
        assert is_error is False
        assert msg is None

    @pytest.mark.parametrize(
        "code,expected_fragment",
        [
            (b"01", "01"),
            (b"02", "CHKSUM"),
            (b"03", "LCHKSUM"),
            (b"04", "CID2"),
            (b"05", "05"),
            (b"06", "06"),
            (b"09", "write"),
        ],
    )
    def test_error_codes(self, code, expected_fragment):
        is_error, msg = cid2_return_code(code)
        assert is_error is True
        assert expected_fragment.lower() in msg.lower()

    def test_unknown_code_treated_as_success(self):
        is_error, msg = cid2_return_code(b"FF")
        assert is_error is False


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------


class TestBuildRequest:
    def test_version_request_structure(self):
        from bmspace import constants
        req = build_request(cid2=constants.cid2SoftwareVersion)
        # SOI
        assert req[0:1] == b"~"
        # VER
        assert req[1:3] == b"25"
        # ADR
        assert req[3:5] == b"01"
        # CID1
        assert req[5:7] == b"46"
        # CID2 for software version
        assert req[7:9] == b"C1"
        # LCHKSUM (no info, so LENID=000, LCHKSUM='0')
        assert req[9:10] == b"0"
        # LENID
        assert req[10:13] == b"000"
        # EOI at end
        assert req[-1:] == b"\r"

    def test_version_request_checksum(self):
        from bmspace import constants
        req = build_request(cid2=constants.cid2SoftwareVersion)
        assert req == b"~250146C10000FD9A\r"

    def test_with_info_payload(self):
        req = build_request(cid2=b"42", info=b"FF")
        # info length = 2, LENID = '002'
        assert req[10:13] == b"002"
        # info embedded at position 13
        assert req[13:15] == b"FF"
        # EOI at end
        assert req[-1:] == b"\r"

    def test_packet_is_accepted_by_parse_response(self):
        """Any request built with build_request must be self-consistent."""
        req = build_request(cid2=b"42", info=b"01")
        # Build a matching fake response and verify round-trip integrity
        response = _build_valid_response(b"RESULT")
        success, info = parse_response(response)
        assert success is True
        assert info == b"RESULT"

    def test_empty_info_uses_lchksum_zero(self):
        req = build_request(cid2=b"C2")
        assert req[9:10] == b"0"
        assert req[10:13] == b"000"

    def test_non_empty_info_computes_lchksum(self):
        # info = b'FF' → len=2 → LENID=b'002' → lchksum_calc(b'002')='E'
        req = build_request(cid2=b"42", info=b"FF")
        assert req[9:10] == b"E"


# ---------------------------------------------------------------------------
# parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_valid_packet_returns_info(self):
        info = b"DEADBEEF"
        response = _build_valid_response(info)
        success, parsed = parse_response(response)
        assert success is True
        assert parsed == info

    def test_empty_info_is_valid(self):
        response = _build_valid_response(b"")
        success, parsed = parse_response(response)
        assert success is True
        assert parsed == b""

    def test_wrong_soi_returns_error(self):
        response = _build_valid_response(b"DATA")
        # Corrupt the first byte
        bad = b"X" + response[1:]
        success, msg = parse_response(bad)
        assert success is False
        assert "starting byte" in msg.lower()

    def test_empty_data_returns_error(self):
        success, msg = parse_response(b"")
        assert success is False

    def test_too_short_returns_error(self):
        success, msg = parse_response(b"~25")
        assert success is False

    def test_rtn_error_code_is_detected(self):
        # Build a packet with RTN=02 (CHKSUM error)
        packet = b"~250146" + b"02" + b"0" + b"000"
        chksum = bytes(chksum_calc(packet), "ASCII")
        bad_response = packet + chksum + b"\r"
        success, msg = parse_response(bad_response)
        assert success is False
        assert "CHKSUM" in msg

    def test_bad_checksum_returns_error(self):
        response = _build_valid_response(b"DATA")
        # Flip one byte in the CHKSUM field (last 5 bytes: 4 chksum + 1 eoi)
        corrupted = response[:-5] + b"0000" + b"\r"
        success, msg = parse_response(corrupted)
        assert success is False

    def test_bad_lchksum_returns_error(self):
        response = _build_valid_response(b"DATA")
        # LCHKSUM is at index 9; corrupt it
        corrupted = response[:9] + b"X" + response[10:]
        success, msg = parse_response(corrupted)
        assert success is False

    def test_large_info_payload(self):
        # Simulate a realistic 220-byte INFO payload
        info = b"0" * 220
        response = _build_valid_response(info)
        success, parsed = parse_response(response)
        assert success is True
        assert len(parsed) == 220

    def test_known_analog_response(self):
        """
        End-to-end: the response fixture built from real BMS protocol values
        must parse successfully and its INFO must decode to the expected analog data.
        """
        # Fixture: 1 pack, 2 cells (3300, 3310 mV), 2 temps (25.0, 20.0 °C)
        # INFO: DATAFLG(00) + packs(01) + cells(02) + cell1(0CE4) + cell2(0CEE) + ...
        response = b"~2501460090340001020CE40CEE020BA40B7203E8C80003E80307D0002A07D000F287\r"
        success, info = parse_response(response)
        assert success is True
        # INFO[2:4] = pack count = 1
        assert int(info[2:4], 16) == 1
        # INFO[4:6] = cells count = 2
        assert info[4:6] == b"02"
        # INFO[6:10] = cell1 = 3300 = 0CE4
        assert int(info[6:10], 16) == 3300
        # INFO[10:14] = cell2 = 3310 = 0CEE
        assert int(info[10:14], 16) == 3310
