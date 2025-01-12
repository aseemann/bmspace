import time
import serial
import json
import logging
from constants import (
    cid2PackNumber,
    cid2SoftwareVersion,
    cid2SerialNumber,
    cid2PackAnalogData,
    cid2PackCapacity,
    cid2WarnInfo,
    warningStates,
    protectState1,
    protectState2,
    controlState,
    faultState,
    warnState1,
    warnState2
)

logging.basicConfig(level=logging.INFO)

class BMS:
    def __init__(self, serial_port, debug_level=0):
        self.serial_port = serial_port
        self.debug_level = debug_level
        self.output = {'errors': []}
        self.connection = None

    def connect(self):
        try:
            self.connection = serial.Serial(self.serial_port, timeout=1)
            return True
        except IOError as e:
            self.output['errors'].append(f"BMS serial error connecting: {e}")
            return False

    def send_data(self, request):
        try:
            self.connection.write(request)
            time.sleep(0.25)
            return True
        except IOError as e:
            self.output['errors'].append(f"BMS serial error: {e}")
            return False

    def receive_data(self):
        try:
            return self.connection.readline()
        except Exception as e:
            self.output['errors'].append(f"BMS receive error: {e}")
            return None

    @staticmethod
    def calculate_checksum(data):
        try:
            chksum = sum(data[1:]) % 65536
            chksum_bin = f"{chksum:016b}"
            flipped = ''.join('1' if bit == '0' else '0' for bit in chksum_bin)
            return f"{int(flipped, 2) + 1:X}"
        except Exception as e:
            raise ValueError(f"Checksum calculation failed: {e}")

    @staticmethod
    def calculate_lchksum(lenid):
        try:
            chksum = sum(int(chr(byte), 16) for byte in lenid) % 16
            flipped = ''.join('1' if bit == '0' else '0' for bit in f"{chksum:04b}")
            return f"{int(flipped, 2) + 1:X}" if int(flipped, 2) + 1 <= 15 else "0"
        except Exception as e:
            raise ValueError(f"LCHKSUM calculation failed: {e}")

    def parse_response(self, data):
        try:
            if data[0] != 0x7E:
                raise ValueError("Invalid start byte")

            length_id = int(data[10:13], 16)
            calc_lchksum = self.calculate_lchksum(data[10:13])

            if data[9] != ord(calc_lchksum):
                raise ValueError("LCHKSUM mismatch")

            info = data[13:13 + length_id]
            calc_chksum = self.calculate_checksum(data[:-5])

            if data[13 + length_id:13 + length_id + 4].decode("ASCII") != calc_chksum:
                raise ValueError("Checksum mismatch")

            return info
        except Exception as e:
            self.output['errors'].append(f"Error parsing response: {e}")
            return None

    def request(self, ver, adr, cid1, cid2, info=b"", lenid=None):
        try:
            if not lenid:
                lenid = f"{len(info):03X}".encode("ASCII")
            lchksum = self.calculate_lchksum(lenid)

            request = (b"\x7e" + ver + adr + cid1 + cid2 + lchksum.encode("ASCII") + lenid + info +
                       self.calculate_checksum(b"\x7e" + ver + adr + cid1 + cid2 + lchksum.encode("ASCII") + lenid + info).encode("ASCII") + b"\x0d")

            if self.send_data(request):
                response = self.receive_data()
                if response:
                    return self.parse_response(response)
            return None
        except Exception as e:
            self.output['errors'].append(f"Request failed: {e}")
            return None

    def get_version(self):
        return self.request(b"\x32\x35", b"\x30\x31", b"\x34\x36", cid2SoftwareVersion)

    def get_serial_number(self):
        return self.request(b"\x32\x35", b"\x30\x31", b"\x34\x36", cid2SerialNumber)

    def get_pack_number(self):
        response = self.request(b"\x32\x35", b"\x30\x31", b"\x34\x36", cid2PackNumber)
        if response:
            try:
                return int(response, 16)
            except ValueError as e:
                self.output['errors'].append(f"Error parsing pack number: {e}")
        return None

    def get_analog_data(self, battery_number):
        battery = bytes(f"{battery_number:02X}", 'ASCII')
        response = self.request(b"\x32\x35", b"\x30\x31", b"\x34\x36", cid2PackAnalogData, battery)
        if response:
            try:
                return self.parse_analog_data(response)
            except Exception as e:
                self.output['errors'].append(f"Error parsing analog data: {e}")
        return None

    def parse_analog_data(self, data):
        try:
            index = 2
            packs = int(data[index:index + 2], 16)
            analog_data = {'packs': packs}
            index += 2

            for pack in range(1, packs + 1):
                cells = int(data[index:index + 2], 16)
                analog_data[f'pack_{pack}'] = {'cells': cells, 'voltages': [], 'temperatures': []}
                index += 2

                for _ in range(cells):
                    voltage = int(data[index:index + 4], 16) / 1000
                    analog_data[f'pack_{pack}']['voltages'].append(voltage)
                    index += 4

                temps = int(data[index:index + 2], 16)
                index += 2
                for _ in range(temps):
                    temperature = (int(data[index:index + 4], 16) - 2730) / 10
                    analog_data[f'pack_{pack}']['temperatures'].append(temperature)
                    index += 4

            return analog_data
        except Exception as e:
            raise ValueError(f"Error parsing analog data: {e}")

    def get_capacity(self):
        response = self.request(b"\x32\x35", b"\x30\x31", b"\x34\x36", cid2PackCapacity)
        if response:
            try:
                return self.parse_capacity_data(response)
            except Exception as e:
                self.output['errors'].append(f"Error parsing capacity data: {e}")
        return None

    def parse_capacity_data(self, data):
        try:
            index = 0
            pack_remain = int(data[index:index + 4], 16) * 10
            index += 4
            pack_full = int(data[index:index + 4], 16) * 10
            index += 4
            pack_design = int(data[index:index + 4], 16) * 10

            soc = round(pack_remain / pack_full * 100, 2)
            soh = round(pack_full / pack_design * 100, 2)

            return {
                'remaining_capacity': pack_remain,
                'full_capacity': pack_full,
                'design_capacity': pack_design,
                'state_of_charge': soc,
                'state_of_health': soh
            }
        except Exception as e:
            raise ValueError(f"Error parsing capacity data: {e}")

    def get_warnings(self):
        response = self.request(b"\x32\x35", b"\x30\x31", b"\x34\x36", cid2WarnInfo, b"FF")
        if response:
            try:
                return self.parse_warning_data(response)
            except Exception as e:
                self.output['errors'].append(f"Error parsing warning data: {e}")
        return None

    def parse_warning_data(self, data):
        try:
            index = 2
            packs = int(data[index:index + 2], 16)
            warnings = {'packs': packs}
            index += 2

            for pack in range(1, packs + 1):
                cells = int(data[index:index + 2], 16)
                index += 2

                warnings[f'pack_{pack}'] = {'cell_warnings': [], 'temp_warnings': []}

                for _ in range(cells):
                    warning = data[index:index + 2]
                    if warning != b'00':
                        warnings[f'pack_{pack}']['cell_warnings'].append(warningStates[warning])
                    index += 2

                temps = int(data[index:index + 2], 16)
                index += 2
                for _ in range(temps):
                    warning = data[index:index + 2]
                    if warning != b'00':
                        warnings[f'pack_{pack}']['temp_warnings'].append(warningStates[warning])
                    index += 2

            return warnings
        except Exception as e:
            raise ValueError(f"Error parsing warning data: {e}")

    def export_to_json(self, filename="bms_data.json"):
        try:
            data = {
                'version': self.get_version(),
                'serial_number': self.get_serial_number(),
                'pack_number': self.get_pack_number(),
                'analog_data': self.get_analog_data(255),
                'capacity': self.get_capacity(),
                'warnings': self.get_warnings()
            }
            json.dumps(data)
        except Exception as e:
            logging.error(f"Failed to export data to JSON: {e}")

if __name__ == "__main__":
    import sys

    bms_serial = sys.argv[1]
    bms = BMS(bms_serial)

    if not bms.connect():
        logging.error("Failed to connect to BMS")
        sys.exit(1)

    bms.export_to_json()
