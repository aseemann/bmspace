#!/usr/bin/env python3
import time
import serial
import json
import sys
import constants
from contextlib import contextmanager

class BmsController:
    def __init__(self, serial_port, debug_level=0):
        self.serial_port = serial_port
        self.debug_level = debug_level
        self.bms = None
        self.bms_connected = False
        self.output = {'errors': []}
        self.bms_version = ''
        self.bms_sn = ''
        self.pack_sn = ''
        self.packs = 1
        self.cells = 13
        self.temps = 6
        self.inc_data = ''

    def connect(self):
        """Connect to the BMS via serial port"""
        try:
            self.bms = serial.Serial(self.serial_port, timeout=1)
            self.bms_connected = True
            return True
        except IOError as msg:
            self.output['errors'].append(f"BMS serial error connecting: {msg}")
            self.bms_connected = False
            return False

    def send_data(self, request=''):
        """Send data to the BMS"""
        try:
            if request:
                self.bms.write(request)
                time.sleep(0.25)
                return True
            return False
        except IOError as e:
            self.output['errors'].append(f"BMS serial error: {e}")
            return False

    def get_data(self):
        """Get data from the BMS"""
        try:
            return self.bms.readline()
        except Exception as e:
            self.output['errors'].append(f"BMS socket receive error: {e}")
            return False

    @staticmethod
    def chksum_calc(data):
        """Calculate checksum for BMS data"""
        try:
            chksum = sum(data[1:]) % 65536
            chksum = '{0:016b}'.format(chksum)

            # Flip bits
            flip_bits = ''.join('1' if bit == '0' else '0' for bit in chksum)

            chksum = int(flip_bits, 2) + 1
            return format(chksum, 'X')
        except Exception as e:
            return False

    @staticmethod
    def lchksum_calc(lenid):
        """Calculate length checksum for BMS data"""
        try:
            chksum = sum(int(chr(b), 16) for b in lenid) % 16
            chksum = '{0:04b}'.format(chksum)

            # Flip bits
            flip_bits = ''.join('1' if bit == '0' else '0' for bit in chksum)

            chksum = int(flip_bits, 2) + 1
            if chksum > 15:
                chksum = 0

            return format(chksum, 'X')
        except Exception:
            return False

    @staticmethod
    def cid2_rtn(rtn):
        """Process return code from BMS"""
        error_codes = {
            b'01': "RTN Error 01: Undefined RTN error",
            b'02': "RTN Error 02: CHKSUM error",
            b'03': "RTN Error 03: LCHKSUM error",
            b'04': "RTN Error 04: CID2 undefined",
            b'05': "RTN Error 05: Undefined error",
            b'06': "RTN Error 06: Undefined error",
            b'09': "RTN Error 09: Operation or write error"
        }

        if rtn == b'00':
            return False, False
        elif rtn in error_codes:
            return True, error_codes[rtn]
        else:
            return False, False

    def parse_data(self, inc_data):
        """Parse data received from BMS"""
        try:
            SOI = hex(ord(inc_data[0:1]))
            if SOI != '0x7e':
                return False, "Incorrect starting byte for incoming data"

            if self.debug_level > 1:
                print("SOI: ", SOI)
                print("VER: ", inc_data[1:3])
                print("ADR: ", inc_data[3:5])
                print("CID1 (Type): ", inc_data[5:7])

            RTN = inc_data[7:9]
            error, info = self.cid2_rtn(RTN)
            if error:
                return False, info

            LCHKSUM = inc_data[9]
            LENID = int(inc_data[10:13], 16)  # amount of bytes, i.e. 2x hex

            calc_LCHKSUM = self.lchksum_calc(inc_data[10:13])
            if calc_LCHKSUM is False:
                return False, "Error calculating LCHKSUM for incoming data"

            if LCHKSUM != ord(calc_LCHKSUM):
                if self.debug_level > 0:
                    print(f"LCHKSUM received: {LCHKSUM} does not match calculated: {ord(calc_LCHKSUM)}")
                return False, f"LCHKSUM received: {LCHKSUM} does not match calculated: {ord(calc_LCHKSUM)}"

            INFO = inc_data[13:13 + LENID]
            CHKSUM = inc_data[13 + LENID:13 + LENID + 4]
            calc_CHKSUM = self.chksum_calc(inc_data[:len(inc_data) - 5])

            if calc_CHKSUM is False:
                return False, "Error calculating CHKSUM"

            if CHKSUM.decode("ASCII") == calc_CHKSUM:
                return True, INFO
            else:
                if self.debug_level > 0:
                    print(f"Received and calculated CHKSUM does not match: Received: {CHKSUM.decode('ASCII')}, Calculated: {calc_CHKSUM}")
                return False, "Checksum error"

        except Exception as e:
            return False, f"Error parsing data: {str(e)}"

    def request(self, ver=b"\x32\x35", adr=b"\x30\x31", cid1=b"\x34\x36", cid2=b"\x43\x31", info=b"", LENID=False):
        """Send a request to the BMS and get the response"""
        request = b'\x7e'
        request += ver
        request += adr
        request += cid1
        request += cid2

        if not LENID:
            LENID = len(info)
            LENID = bytes(format(LENID, '03X'), "ASCII")

        if LENID == b'000':
            LCHKSUM = '0'
        else:
            LCHKSUM = self.lchksum_calc(LENID)
            if LCHKSUM is False:
                return False, "Error calculating LCHKSUM"

        request += bytes(LCHKSUM, "ASCII")
        request += LENID
        request += info

        CHKSUM = bytes(self.chksum_calc(request), "ASCII")
        if CHKSUM is False:
            return False, "Error calculating CHKSUM"

        request += CHKSUM
        request += b'\x0d'

        if self.debug_level > 2:
            print("-> Outgoing Data: ", request)

        if not self.send_data(request):
            self.bms_connected = False
            self.output['errors'].append("Error sending data to BMS")
            return False, "Error, connection to BMS lost"

        self.inc_data = self.get_data()

        if not self.inc_data:
            self.output['errors'].append("Error retrieving data from BMS")
            return False, "Error retrieving data from BMS"

        if self.debug_level > 2:
            print("<- Incoming data: ", self.inc_data)

        success, INFO = self.parse_data(self.inc_data)
        return success, INFO

    def get_pack_number(self):
        """Get the number of battery packs"""
        success, INFO = self.request(cid2=constants.cid2PackNumber)

        if not success:
            return False, INFO

        try:
            pack_number = int(INFO, 16)
            return success, pack_number
        except Exception:
            self.output['errors'].append("Error extracting total battery count in pack")
            return False, "Error extracting total battery count in pack"

    def get_version(self):
        """Get BMS software version"""
        success, INFO = self.request(cid2=constants.cid2SoftwareVersion)

        if not success:
            return False, INFO

        try:
            self.bms_version = bytes.fromhex(INFO.decode("ascii")).decode("ASCII")
            self.output['bms_version'] = str(self.bms_version).rstrip()
            return success, self.bms_version
        except Exception:
            return False, "Error extracting BMS version"

    def get_serial(self):
        """Get BMS and pack serial numbers"""
        success, INFO = self.request(cid2=constants.cid2SerialNumber)

        if not success:
            self.output['error'] = INFO
            return False, INFO, False

        try:
            self.bms_sn = bytes.fromhex(INFO[0:30].decode("ascii")).decode("ASCII")
            self.pack_sn = bytes.fromhex(INFO[40:68].decode("ascii")).decode("ASCII")
            self.output['bms_sn'] = str(self.bms_sn).strip()
            self.output['pack_sn'] = str(self.pack_sn).strip()
            return success, self.bms_sn, self.pack_sn
        except Exception:
            self.output['errors'].append("Error extracting BMS version")
            return False, "Error extracting BMS version", False

    def get_analog_data(self, bat_number):
        """Get analog data from the BMS"""
        byte_index = 2
        i_pack = []
        v_pack = []
        i_remain_cap = []
        i_design_cap = []
        cycles = []
        i_full_cap = []
        soc = []
        soh = []

        battery = bytes(format(bat_number, '02X'), 'ASCII')
        success, self.inc_data = self.request(cid2=constants.cid2PackAnalogData, info=battery)

        if not success:
            return False, self.inc_data

        try:
            self.packs = int(self.inc_data[byte_index:byte_index + 2], 16)
            self.output['packs'] = self.packs
            byte_index += 2

            v_cell = {}
            t_cell = {}

            for p in range(1, self.packs + 1):
                if p > 1:
                    cells_prev = self.cells

                self.cells = int(self.inc_data[byte_index:byte_index + 2], 16)

                if p > 1:
                    if self.cells != cells_prev:
                        byte_index += 2
                        self.cells = int(self.inc_data[byte_index:byte_index + 2], 16)
                        if self.cells != cells_prev:
                            self.output['errors'].append("Error parsing BMS analog data: Cannot read multiple packs")
                            return False, "Error parsing BMS analog data: Cannot read multiple packs"

                self.output.setdefault('pack', {})[p] = {'cells': self.cells, 'cell': {}}
                byte_index += 2

                # Process cell voltages
                for i in range(0, self.cells):
                    v_cell[(p - 1, i)] = int(self.inc_data[byte_index:byte_index + 4], 16)
                    byte_index += 4
                    self.output['pack'][p]['cell'][str(i + 1)] = str(v_cell[(p - 1, i)])

                # Process temperatures
                self.temps = int(self.inc_data[byte_index:byte_index + 2], 16)
                self.output['pack'][p]['temps'] = self.temps
                self.output['pack'][p]['temp'] = {}
                byte_index += 2

                for i in range(0, self.temps):
                    t_cell[(p - 1, i)] = (int(self.inc_data[byte_index:byte_index + 4], 16) - 2730) / 10
                    byte_index += 4
                    self.output['pack'][p]['temp'][i + 1] = t_cell[(p - 1, i)]

                # Process pack current
                i_pack.append(int(self.inc_data[byte_index:byte_index + 4], 16))
                byte_index += 4
                if i_pack[p - 1] >= 32768:
                    i_pack[p - 1] = -1 * (65535 - i_pack[p - 1])
                i_pack[p - 1] = i_pack[p - 1] / 100
                self.output['pack'][p]['i_pack'] = i_pack[p - 1]

                # Process pack voltage
                v_pack.append(int(self.inc_data[byte_index:byte_index + 4], 16) / 1000)
                byte_index += 4
                self.output['pack'][p]['v_pack'] = v_pack[p - 1]

                # Process remaining capacity
                i_remain_cap.append(int(self.inc_data[byte_index:byte_index + 4], 16) * 10)
                byte_index += 4
                self.output['pack'][p]['i_remain_cap'] = i_remain_cap[p - 1]

                byte_index += 2  # Manual: Define number P = 3

                # Process full capacity
                i_full_cap.append(int(self.inc_data[byte_index:byte_index + 4], 16) * 10)
                byte_index += 4
                self.output['pack'][p]['i_full_cap'] = i_full_cap[p - 1]

                # Calculate SOC
                soc.append(round(i_remain_cap[p - 1] / i_full_cap[p - 1] * 100, 2))
                self.output['pack'][p]['soc'] = soc[p - 1]

                # Process cycles
                cycles.append(int(self.inc_data[byte_index:byte_index + 4], 16))
                byte_index += 4
                self.output['pack'][p]['cycles'] = cycles[p - 1]

                # Process design capacity
                i_design_cap.append(int(self.inc_data[byte_index:byte_index + 4], 16) * 10)
                byte_index += 4
                self.output['pack'][p]['i_design_cap'] = i_design_cap[p - 1]

                # Calculate SOH
                soh.append(round(i_full_cap[p - 1] / i_design_cap[p - 1] * 100, 2))
                self.output['pack'][p]['soh'] = soh[p - 1]

                byte_index += 2

        except Exception as e:
            self.output['errors'].append(f"Error parsing BMS analog data: {e}")
            return False, f"Error parsing BMS analog data: {str(e)}"

        return True, True

    def get_pack_capacity(self):
        """Get pack capacity information"""
        byte_index = 0

        success, self.inc_data = self.request(cid2=constants.cid2PackCapacity)

        if not success:
            return False, self.inc_data

        try:
            # Process pack remaining capacity
            pack_remain_cap = int(self.inc_data[byte_index:byte_index + 4], 16) * 10
            byte_index += 4
            self.output['pack_remain_cap'] = pack_remain_cap

            # Process pack full capacity
            pack_full_cap = int(self.inc_data[byte_index:byte_index + 4], 16) * 10
            byte_index += 4
            self.output['pack_full_cap'] = pack_full_cap

            # Process pack design capacity
            pack_design_cap = int(self.inc_data[byte_index:byte_index + 4], 16) * 10
            byte_index += 4
            self.output['pack_design_cap'] = pack_design_cap

            # Calculate pack SOC and SOH
            pack_soc = round(pack_remain_cap / pack_full_cap * 100, 2)
            self.output['pack_soc'] = pack_soc

            pack_soh = round(pack_full_cap / pack_design_cap * 100, 2)
            self.output['pack_soh'] = pack_soh

        except Exception as e:
            self.output['errors'].append(f"Error parsing BMS pack capacity data: {e}")
            return False, f"Error parsing BMS pack capacity data: {str(e)}"

        return True, True

    def get_warn_info(self):
        """Get warning information from the BMS"""
        byte_index = 2
        warnings = ""

        success, self.inc_data = self.request(cid2=constants.cid2WarnInfo, info=b'FF')

        if not success:
            return False, self.inc_data

        try:
            packs_w = int(self.inc_data[byte_index:byte_index + 2], 16)
            self.output['packs_for_warnings'] = self.packs
            byte_index += 2

            for p in range(1, self.packs + 1):
                cells_w = int(self.inc_data[byte_index:byte_index + 2], 16)
                byte_index += 2

                # Process cell warnings
                for c in range(1, cells_w + 1):
                    if self.inc_data[byte_index:byte_index + 2] != b'00':
                        warn = constants.warningStates[self.inc_data[byte_index:byte_index + 2]]
                        warnings += f"cell {c} {warn}, "
                    byte_index += 2

                # Process temperature warnings
                temps_w = int(self.inc_data[byte_index:byte_index + 2], 16)
                byte_index += 2

                for t in range(1, temps_w + 1):
                    if self.inc_data[byte_index:byte_index + 2] != b'00':
                        warn = constants.warningStates[self.inc_data[byte_index:byte_index + 2]]
                        warnings += f"temp {t} {warn}, "
                    byte_index += 2

                # Process charge current warning
                if self.inc_data[byte_index:byte_index + 2] != b'00':
                    warn = constants.warningStates[self.inc_data[byte_index:byte_index + 2]]
                    warnings += f"charge current {warn}, "
                byte_index += 2

                # Process total voltage warning
                if self.inc_data[byte_index:byte_index + 2] != b'00':
                    warn = constants.warningStates[self.inc_data[byte_index:byte_index + 2]]
                    warnings += f"total voltage {warn}, "
                byte_index += 2

                # Process discharge current warning
                if self.inc_data[byte_index:byte_index + 2] != b'00':
                    warn = constants.warningStates[self.inc_data[byte_index:byte_index + 2]]
                    warnings += f"discharge current {warn}, "
                byte_index += 2

                # Process protection state 1
                protect_state1 = ord(bytes.fromhex(self.inc_data[byte_index:byte_index + 2].decode('ascii')))
                if protect_state1 > 0:
                    warnings += "Protection State 1: "
                    for x in range(0, 8):
                        if (protect_state1 & (1 << x)):
                            warnings += constants.protectState1[x + 1] + " | "
                    warnings = warnings.rstrip("| ")
                    warnings += ", "

                # Store protection state bits in output
                self.output['pack'][p].setdefault('wrn', {})
                self.output['pack'][p]['wrn']['prot_shot_circuit'] = protect_state1 >> 6 & 1
                self.output['pack'][p]['wrn']['prot_discharge_current'] = protect_state1 >> 5 & 1
                self.output['pack'][p]['wrn']['prot_charge_current'] = protect_state1 >> 4 & 1
                byte_index += 2

                # Process protection state 2
                protect_state2 = ord(bytes.fromhex(self.inc_data[byte_index:byte_index + 2].decode('ascii')))
                if protect_state2 > 0:
                    warnings += "Protection State 2: "
                    for x in range(0, 8):
                        if (protect_state2 & (1 << x)):
                            warnings += constants.protectState2[x + 1] + " | "
                    warnings = warnings.rstrip("| ")
                    warnings += ", "

                self.output['pack'][p]['wrn']['fully'] = protect_state2 >> 7 & 1
                byte_index += 2

                # Process instruction state
                instruction_state = ord(bytes.fromhex(self.inc_data[byte_index:byte_index + 2].decode('ascii')))
                self.output['pack'][p]['wrn']['current_limit'] = instruction_state >> 0 & 1
                self.output['pack'][p]['wrn']['charge_fet'] = instruction_state >> 1 & 1
                self.output['pack'][p]['wrn']['discharge_fet'] = instruction_state >> 2 & 1
                self.output['pack'][p]['wrn']['pack_indicate'] = instruction_state >> 3 & 1
                self.output['pack'][p]['wrn']['reverse'] = instruction_state >> 4 & 1
                self.output['pack'][p]['wrn']['ac_in'] = instruction_state >> 5 & 1
                self.output['pack'][p]['wrn']['heart'] = instruction_state >> 7 & 1
                byte_index += 2

                # Process control state
                control_state = ord(bytes.fromhex(self.inc_data[byte_index:byte_index + 2].decode('ascii')))
                if control_state > 0:
                    warnings += "Control State: "
                    for x in range(0, 8):
                        if (control_state & (1 << x)):
                            warnings += constants.controlState[x + 1] + " | "
                    warnings = warnings.rstrip("| ")
                    warnings += ", "
                byte_index += 2

                # Process fault state
                fault_state = ord(bytes.fromhex(self.inc_data[byte_index:byte_index + 2].decode('ascii')))
                if fault_state > 0:
                    warnings += "Fault State: "
                    for x in range(0, 8):
                        if (fault_state & (1 << x)):
                            warnings += constants.faultState[x + 1] + " | "
                    warnings = warnings.rstrip("| ")
                    warnings += ", "
                byte_index += 2

                # Process balance states
                balance_state1 = '{0:08b}'.format(int(self.inc_data[byte_index:byte_index + 2], 16))
                byte_index += 2

                balance_state2 = '{0:08b}'.format(int(self.inc_data[byte_index:byte_index + 2], 16))
                byte_index += 2

                # Process warning states
                warn_state1 = ord(bytes.fromhex(self.inc_data[byte_index:byte_index + 2].decode('ascii')))
                if warn_state1 > 0:
                    warnings += "Warning State 1: "
                    for x in range(0, 8):
                        if (warn_state1 & (1 << x)):
                            warnings += constants.warnState1[x + 1] + " | "
                    warnings = warnings.rstrip("| ")
                    warnings += ", "
                byte_index += 2

                warn_state2 = ord(bytes.fromhex(self.inc_data[byte_index:byte_index + 2].decode('ascii')))
                if warn_state2 > 0:
                    warnings += "Warning State 2: "
                    for x in range(0, 8):
                        if (warn_state2 & (1 << x)):
                            warnings += constants.warnState2[x + 1] + " | "
                    warnings = warnings.rstrip("| ")
                    warnings += ", "
                byte_index += 2

                warnings = warnings.rstrip(", ")

                self.output['pack'][p]['warnings'] = warnings
                self.output['pack'][p]['balancing_1'] = balance_state1
                self.output['pack'][p]['balancing_2'] = balance_state2
                warnings = ""

        except Exception as e:
            self.output['errors'].append(f"Error parsing BMS warning data: {e}")
            return False, f"Error parsing BMS warning data: {str(e)}"

        return True, True

    def close(self):
        """Close the BMS connection"""
        if self.bms:
            try:
                self.bms.close()
            except Exception:
                pass
            self.bms = None
            self.bms_connected = False

    def get_all_data(self):
        """Get all data from the BMS"""
        if not self.connect():
            self.output['errors'].append("BMS not connected")
            return False

        # Get version information
        success, data = self.get_version()
        if not success:
            self.output['errors'].append("Error retrieving BMS version number")

        time.sleep(0.1)

        # Get serial numbers
        success, bms_sn, pack_sn = self.get_serial()
        if not success:
            self.output['errors'].append("Error retrieving BMS and pack serial numbers")
            self.close()
            return False

        # Get analog data
        success, data = self.get_analog_data(bat_number=255)
        if not success:
            self.output['errors'].append(f"Error retrieving BMS analog data: {data}")

        # Get pack capacity
        success, data = self.get_pack_capacity()
        if not success:
            self.output['errors'].append(f"Error retrieving BMS pack capacity: {data}")

        # Get warning information
        success, data = self.get_warn_info()
        if not success:
            self.output['errors'].append(f"Error retrieving BMS warning info: {data}")

        return True

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print(json.dumps({'errors': ['Serial port not specified']}))
        sys.exit(1)

    serial_port = sys.argv[1]

    # Create BMS controller
    bms_controller = BmsController(serial_port)

    # Get all data
    bms_controller.get_all_data()

    # Print output as JSON
    print(json.dumps(bms_controller.output))

    # Close connection
    bms_controller.close()

if __name__ == "__main__":
    main()
