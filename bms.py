import time
import serial
import json
import sys
import constants

scan_interval = 1
bms_serial = sys.argv[1]
debug_output = 0
output = {'errors': []}

bms_version = ''
bms_sn = ''
pack_sn = ''
packs = 1
cells = 13
temps = 6
inc_data = ''

def bms_connect():
    try:
        s = serial.Serial(bms_serial, timeout=1)
        return s, True
    except IOError as msg:
        output['errors'].append("BMS serial error connecting: %s" % msg)
        return False, False


def bms_sendData(comms, request=''):
    try:
        if len(request) > 0:
            comms.write(request)
            time.sleep(0.25)
            return True
    except IOError as e:
        output['errors'].append("BMS serial error: %s" % e)
        return False


def bms_get_data(comms):
    global inc_data
    try:
        return comms.readline()
    except Exception as e:
        output['errors'].append("BMS socket receive error: %s" % e)
        return False


def chksum_calc(data):
    global debug_output
    chksum = 0

    try:

        for element in range(1, len(data)):  #-5):
            chksum += (data[element])

        chksum = chksum % 65536
        chksum = '{0:016b}'.format(chksum)

        flip_bits = ''
        for i in chksum:
            if i == '0':
                flip_bits += '1'
            else:
                flip_bits += '0'

        chksum = flip_bits
        chksum = int(chksum, 2) + 1

        chksum = format(chksum, 'X')

    except Exception as e:
        output['errors'].append("Error calculating CHKSUM using data: %s" % data)
        output['errors'].append("Error details: %s" % e)
        return (False)

    return (chksum)


def cid2_rtn(rtn):
    if rtn == b'00':
        return False, False
    elif rtn == b'01':
        return True, "RTN Error 01: Undefined RTN error"
    elif rtn == b'02':
        return True, "RTN Error 02: CHKSUM error"
    elif rtn == b'03':
        return True, "RTN Error 03: LCHKSUM error"
    elif rtn == b'04':
        return True, "RTN Error 04: CID2 undefined"
    elif rtn == b'05':
        return True, "RTN Error 05: Undefined error"
    elif rtn == b'06':
        return True, "RTN Error 06: Undefined error"
    elif rtn == b'09':
        return True, "RTN Error 09: Operation or write error"
    else:
        return False, False


def bms_parse_data(inc_data):
    global debug_output

    try:

        SOI = hex(ord(inc_data[0:1]))
        if SOI != '0x7e':
            output['errors'].append("Incorrect starting byte for incoming data")
            return False, "Incorrect starting byte for incoming data"

        if debug_output > 1:
            print("SOI: ", SOI)
            print("VER: ", inc_data[1:3])
            print("ADR: ", inc_data[3:5])
            print("CID1 (Type): ", inc_data[5:7])

        RTN = inc_data[7:9]
        error, info = cid2_rtn(RTN)
        if error:
            print(error)
            raise Exception(error)

        LCHKSUM = inc_data[9]

        if debug_output > 1:
            print("RTN: ", RTN)
            print("LENGTH: ", inc_data[9:13])
            print(" - LCHKSUM: ", LCHKSUM)
            print(" - LENID: ", inc_data[10:13])

        LENID = int(inc_data[10:13], 16)  #amount of bytes, i.e. 2x hex

        calc_LCHKSUM = lchksum_calc(inc_data[10:13])
        if calc_LCHKSUM == False:
            return False, "Error calculating LCHKSUM for incoming data"

        if LCHKSUM != ord(calc_LCHKSUM):
            if debug_output > 0:
                print("LCHKSUM received: " + str(LCHKSUM) + " does not match calculated: " + str(ord(calc_LCHKSUM)))
            return (
                False, "LCHKSUM received: " + str(LCHKSUM) + " does not match calculated: " + str(ord(calc_LCHKSUM)))

        if debug_output > 1:
            print(" - LENID (int): ", LENID)

        INFO = inc_data[13:13 + LENID]

        if debug_output > 1:
            print("INFO: ", INFO)

        CHKSUM = inc_data[13 + LENID:13 + LENID + 4]

        if debug_output > 1:
            print("CHKSUM: ", CHKSUM)

        calc_CHKSUM = chksum_calc(inc_data[:len(inc_data) - 5])

        if debug_output > 1:
            print("Calc CHKSUM: ", calc_CHKSUM)
    except Exception as e:
        if debug_output > 0:
            print("Error1 calculating CHKSUM using data: ", inc_data)
        return False, "Error1 calculating CHKSUM: " + str(e)

    if calc_CHKSUM == False:
        if debug_output > 0:
            print("Error2 calculating CHKSUM using data: ", inc_data)
        return False, "Error2 calculating CHKSUM"

    if CHKSUM.decode("ASCII") == calc_CHKSUM:
        return True, INFO
    else:
        if debug_output > 0:
            print("Received and calculated CHKSUM does not match: Received: " + CHKSUM.decode(
                "ASCII") + ", Calculated: " + calc_CHKSUM)
            print("...for incoming data: " + str(inc_data) + " |Hex: " + str(inc_data.hex(' ')))
            print("Length of incoming data as measured: " + str(len(inc_data)))
            print("SOI: ", SOI)
            print("VER: ", inc_data[1:3])
            print("ADR: ", inc_data[3:5])
            print("CID1 (Type): ", inc_data[5:7])
            print("RTN (decode!): ", RTN)
            print("LENGTH: ", inc_data[9:13])
            print(" - LCHKSUM: ", inc_data[9])
            print(" - LENID: ", inc_data[10:13])
            print(" - LENID (int): ", int(inc_data[10:13], 16))
            print("INFO: ", INFO)
            print("CHKSUM: ", CHKSUM)
        return False, "Checksum error"


def lchksum_calc(lenid):
    chksum = 0

    try:
        for element in range(0, len(lenid)):
            chksum += int(chr(lenid[element]), 16)

        chksum = chksum % 16
        chksum = '{0:04b}'.format(chksum)

        flip_bits = ''
        for i in chksum:
            if i == '0':
                flip_bits += '1'
            else:
                flip_bits += '0'

        chksum = flip_bits
        chksum = int(chksum, 2)

        chksum += 1

        if chksum > 15:
            chksum = 0

        chksum = format(chksum, 'X')

    except:
        output['errors'].append("Error calculating LCHKSUM using LENID: %s" % lenid)
        return False

    return chksum


def bms_request(bms, ver=b"\x32\x35", adr=b"\x30\x31", cid1=b"\x34\x36", cid2=b"\x43\x31", info=b"", LENID=False):
    global bms_connected
    global debug_output
    global inc_data

    request = b'\x7e'
    request += ver
    request += adr
    request += cid1
    request += cid2

    if not (LENID):
        LENID = len(info)
        LENID = bytes(format(LENID, '03X'), "ASCII")

    if LENID == b'000':
        LCHKSUM = '0'
    else:
        LCHKSUM = lchksum_calc(LENID)
        if LCHKSUM == False:
            return False, "Error calculating LCHKSUM)"
    request += bytes(LCHKSUM, "ASCII")
    request += LENID
    request += info
    CHKSUM = bytes(chksum_calc(request), "ASCII")
    if CHKSUM == False:
        return False, "Error calculating CHKSUM)"
    request += CHKSUM
    request += b'\x0d'

    if debug_output > 2:
        print("-> Outgoing Data: ", request)

    if not bms_sendData(bms, request):
        bms_connected = False
        output['errors'].append("Error sending data to BMS")
        return False, "Error, connection to BMS lost"

    inc_data = bms_get_data(bms)

    if not inc_data:
        output['errors'].append("Error retrieving data from BMS")
        return False, "Error retrieving data from BMS"

    if debug_output > 2:
        print("<- Incoming data: ", inc_data)

    success, INFO = bms_parse_data(inc_data)

    return (success, INFO)


def bms_getPackNumber(bms):
    success, INFO = bms_request(bms, cid2=constants.cid2PackNumber)

    if not success:
        return False, INFO

    try:
        packNumber = int(INFO, 16)
    except:
        output['errors'].append("Error extracting total battery count in pack")
        return False, "Error extracting total battery count in pack"

    return success, packNumber


def bms_getVersion(comms):
    global bms_version

    success, INFO = bms_request(bms, cid2=constants.cid2SoftwareVersion)

    if not success:
        return False, INFO

    try:

        bms_version = bytes.fromhex(INFO.decode("ascii")).decode("ASCII")
        output['bms_version'] = str(bms_version).rstrip()
    except:
        return False, "Error extracting BMS version"

    return success, bms_version


def bms_getSerial(comms):
    global bms_sn
    global pack_sn

    success, INFO = bms_request(bms, cid2=constants.cid2SerialNumber)

    if not success:
        output['error'] = INFO
        return False, INFO, False

    try:
        bms_sn = bytes.fromhex(INFO[0:30].decode("ascii")).decode("ASCII")
        pack_sn = bytes.fromhex(INFO[40:68].decode("ascii")).decode("ASCII")
        output['bms_sn'] = str(bms_sn).strip()
        output['pack_sn'] = str(pack_sn).strip()
    except:
        output['errors'].append("Error extracting BMS version")
        return False, "Error extracting BMS version", False

    return success, bms_sn, pack_sn


def bms_getAnalogData(bms, batNumber):
    global cells
    global temps
    global packs
    global inc_data
    byte_index = 2
    i_pack = []
    v_pack = []
    i_remain_cap = []
    i_design_cap = []
    cycles = []
    i_full_cap = []
    soc = []
    soh = []

    battery = bytes(format(batNumber, '02X'), 'ASCII')

    success, inc_data = bms_request(bms, cid2=constants.cid2PackAnalogData, info=battery)

    if not success:
        return False, inc_data

    try:

        packs = int(inc_data[byte_index:byte_index + 2], 16)
        output['packs'] = packs
        byte_index += 2

        v_cell = {}
        t_cell = {}

        for p in range(1, packs + 1):

            if p > 1:
                cells_prev = cells

            cells = int(inc_data[byte_index:byte_index + 2], 16)

            if p > 1:
                if cells != cells_prev:
                    byte_index += 2
                    cells = int(inc_data[byte_index:byte_index + 2], 16)
                    if cells != cells_prev:
                        output['errors'].append("Error parsing BMS analog data: Cannot read multiple packs");
                        return (False, "Error parsing BMS analog data: Cannot read multiple packs")

            output['pack'] = {}
            output['pack'][p] = {}
            output['pack'][p]['cells'] = cells
            output['pack'][p]['cell'] = {}

            byte_index += 2

            for i in range(0, cells):
                v_cell[(p - 1, i)] = int(inc_data[byte_index:byte_index + 4], 16)
                byte_index += 4
                output['pack'][p]['cell'][str(i + 1)] = str(v_cell[(p - 1, i)])

            temps = int(inc_data[byte_index:byte_index + 2], 16)
            output['pack'][p]['temps'] = temps
            output['pack'][p]['temp'] = {}
            byte_index += 2

            for i in range(0, temps):  # temps-2
                t_cell[(p - 1, i)] = (int(inc_data[byte_index:byte_index + 4], 16) - 2730) / 10
                byte_index += 4
                output['pack'][p]['temp'][i + 1] = t_cell[(p - 1, i)]

            i_pack.append(int(inc_data[byte_index:byte_index + 4], 16))
            byte_index += 4
            if i_pack[p - 1] >= 32768:
                i_pack[p - 1] = -1 * (65535 - i_pack[p - 1])
            i_pack[p - 1] = i_pack[p - 1] / 100
            output['pack'][p]['i_pack'] = i_pack[p - 1]

            v_pack.append(int(inc_data[byte_index:byte_index + 4], 16) / 1000)
            byte_index += 4
            output['pack'][p]['v_pack'] = v_pack[p - 1]

            i_remain_cap.append(int(inc_data[byte_index:byte_index + 4], 16) * 10)
            byte_index += 4
            output['pack'][p]['i_remain_cap'] = i_remain_cap[p - 1]

            byte_index += 2  # Manual: Define number P = 3

            i_full_cap.append(int(inc_data[byte_index:byte_index + 4], 16) * 10)
            byte_index += 4
            output['pack'][p]['i_full_cap'] = i_full_cap[p - 1]

            soc.append(round(i_remain_cap[p - 1] / i_full_cap[p - 1] * 100, 2))
            output['pack'][p]['soc'] = soc[p - 1]

            cycles.append(int(inc_data[byte_index:byte_index + 4], 16))
            byte_index += 4
            output['pack'][p]['cycles'] = cycles[p - 1]

            i_design_cap.append(int(inc_data[byte_index:byte_index + 4], 16) * 10)
            byte_index += 4
            output['pack'][p]['i_design_cap'] = i_design_cap[p - 1]

            soh.append(round(i_full_cap[p - 1] / i_design_cap[p - 1] * 100, 2))
            output['pack'][p]['soh'] = soh[p - 1]

            byte_index += 2

    except Exception as e:
        output['errors'].append("Error parsing BMS analog data: %s" % e)
        return False, "Error parsing BMS analog data: " + str(e)

    return True, True


def bms_getPackCapacity(bms):
    byte_index = 0

    success, inc_data = bms_request(bms,
                                    cid2=constants.cid2PackCapacity)  # Seem to always reply with pack 1 data, even with ADR= 0 or FF and INFO= '' or FF

    if not success:
        return False, inc_data

    try:

        pack_remain_cap = int(inc_data[byte_index:byte_index + 4], 16) * 10
        byte_index += 4
        output['pack_remain_cap'] = pack_remain_cap

        pack_full_cap = int(inc_data[byte_index:byte_index + 4], 16) * 10
        byte_index += 4
        output['pack_full_cap'] = pack_full_cap

        pack_design_cap = int(inc_data[byte_index:byte_index + 4], 16) * 10
        byte_index += 4
        output['pack_design_cap'] = pack_design_cap

        pack_soc = round(pack_remain_cap / pack_full_cap * 100, 2)
        output['pack_soc'] = pack_soc

        pack_soh = round(pack_full_cap / pack_design_cap * 100, 2)
        output['pack_soh'] = pack_soh

    except Exception as e:
        output['errors'].append("Error parsing BMS pack capacity data: %s" % e)
        return False, "Error parsing BMS pack capacity data: " + str(e)

    return True, True


def bms_getWarnInfo(bms):
    byte_index = 2
    packsW = 1
    warnings = ""

    success, inc_data = bms_request(bms, cid2=constants.cid2WarnInfo, info=b'FF')

    if not success:
        return False, inc_data

    try:

        packsW = int(inc_data[byte_index:byte_index + 2], 16)
        output['packs_for_warnings'] = packs

        byte_index += 2

        for p in range(1, packs + 1):

            cellsW = int(inc_data[byte_index:byte_index + 2], 16)
            byte_index += 2

            for c in range(1, cellsW + 1):

                if inc_data[byte_index:byte_index + 2] != b'00':
                    warn = constants.warningStates[inc_data[byte_index:byte_index + 2]]
                    warnings += "cell " + str(c) + " " + warn + ", "
                byte_index += 2

            tempsW = int(inc_data[byte_index:byte_index + 2], 16)
            byte_index += 2

            for t in range(1, tempsW + 1):

                if inc_data[byte_index:byte_index + 2] != b'00':
                    warn = constants.warningStates[inc_data[byte_index:byte_index + 2]]
                    warnings += "temp " + str(t) + " " + warn + ", "
                byte_index += 2

            if inc_data[byte_index:byte_index + 2] != b'00':
                warn = constants.warningStates[inc_data[byte_index:byte_index + 2]]
                warnings += "charge current " + warn + ", "
            byte_index += 2

            if inc_data[byte_index:byte_index + 2] != b'00':
                warn = constants.warningStates[inc_data[byte_index:byte_index + 2]]
                warnings += "total voltage " + warn + ", "
            byte_index += 2

            if inc_data[byte_index:byte_index + 2] != b'00':
                warn = constants.warningStates[inc_data[byte_index:byte_index + 2]]
                warnings += "discharge current " + warn + ", "
            byte_index += 2

            protectState1 = ord(bytes.fromhex(inc_data[byte_index:byte_index + 2].decode('ascii')))
            if protectState1 > 0:
                warnings += "Protection State 1: "
                for x in range(0, 8):
                    if (protectState1 & (1 << x)):
                        warnings += constants.protectState1[x + 1] + " | "
                warnings = warnings.rstrip("| ")
                warnings += ", "
            output['pack'][p]['wrn'] = {}
            output['pack'][p]['wrn']['prot_shot_circuit'] = protectState1 >> 6 & 1
            output['pack'][p]['wrn']['prot_discharge_current'] = protectState1 >> 5 & 1
            output['pack'][p]['wrn']['prot_charge_current'] = protectState1 >> 4 & 1
            byte_index += 2

            protectState2 = ord(bytes.fromhex(inc_data[byte_index:byte_index + 2].decode('ascii')))
            if protectState2 > 0:
                warnings += "Protection State 2: "
                for x in range(0, 8):
                    if (protectState2 & (1 << x)):
                        warnings += constants.protectState2[x + 1] + " | "
                warnings = warnings.rstrip("| ")
                warnings += ", "
            output['pack'][p]['wrn']['fully'] = protectState2 >> 7 & 1
            byte_index += 2

            instructionState = ord(bytes.fromhex(inc_data[byte_index:byte_index + 2].decode('ascii')))
            output['pack'][p]['wrn']['current_limit'] = instructionState >> 0 & 1
            output['pack'][p]['wrn']['charge_fet'] = instructionState >> 1 & 1
            output['pack'][p]['wrn']['discharge_fet'] = instructionState >> 2 & 1
            output['pack'][p]['wrn']['pack_indicate'] = instructionState >> 3 & 1
            output['pack'][p]['wrn']['reverse'] = instructionState >> 4 & 1
            output['pack'][p]['wrn']['ac_in'] = instructionState >> 5 & 1
            output['pack'][p]['wrn']['heart'] = instructionState >> 7 & 1
            byte_index += 2

            controlState = ord(bytes.fromhex(inc_data[byte_index:byte_index + 2].decode('ascii')))
            if controlState > 0:
                warnings += "Control State: "
                for x in range(0, 8):
                    if (controlState & (1 << x)):
                        warnings += constants.controlState[x + 1] + " | "
                warnings = warnings.rstrip("| ")
                warnings += ", "
            byte_index += 2

            faultState = ord(bytes.fromhex(inc_data[byte_index:byte_index + 2].decode('ascii')))
            if faultState > 0:
                warnings += "Fault State: "
                for x in range(0, 8):
                    if (faultState & (1 << x)):
                        warnings += constants.faultState[x + 1] + " | "
                warnings = warnings.rstrip("| ")
                warnings += ", "
            byte_index += 2

            balanceState1 = '{0:08b}'.format(int(inc_data[byte_index:byte_index + 2], 16))
            byte_index += 2

            balanceState2 = '{0:08b}'.format(int(inc_data[byte_index:byte_index + 2], 16))
            byte_index += 2

            warnState1 = ord(bytes.fromhex(inc_data[byte_index:byte_index + 2].decode('ascii')))
            if warnState1 > 0:
                warnings += "Warning State 1: "
                for x in range(0, 8):
                    if (warnState1 & (1 << x)):
                        warnings += constants.warnState1[x + 1] + " | "
                warnings = warnings.rstrip("| ")
                warnings += ", "
            byte_index += 2

            warnState2 = ord(bytes.fromhex(inc_data[byte_index:byte_index + 2].decode('ascii')))
            if warnState2 > 0:
                warnings += "Warning State 2: "
                for x in range(0, 8):
                    if (warnState2 & (1 << x)):
                        warnings += constants.warnState2[x + 1] + " | "
                warnings = warnings.rstrip("| ")
                warnings += ", "
            byte_index += 2

            warnings = warnings.rstrip(", ")

            output['pack'][p]['warnings'] = warnings
            output['pack'][p]['balancing_1'] = balanceState1
            output['pack'][p]['balancing_2'] = balanceState2
            warnings = ""

    except Exception as e:
        output['errors'].append("Error parsing BMS warning data: %s" % e)
        return False, "Error parsing BMS warning data: " + str(e)

    return True, True


bms, bms_connected = bms_connect()

success, data = bms_getVersion(bms)
if not success:
    output['errors'].append("Error retrieving BMS version number")

time.sleep(0.1)
success, bms_sn, pack_sn = bms_getSerial(bms)
if not success:
    output['errors'].append("Error retrieving BMS and pack serial numbers")
    quit()

if bms_connected:
    success, data = bms_getAnalogData(bms, batNumber=255)
    if not success:
        output['errors'].append("Error retrieving BMS analog data: " + data)
    success, data = bms_getPackCapacity(bms)
    if not success:
        output['errors'].append("Error retrieving BMS pack capacity: " + data)
    success, data = bms_getWarnInfo(bms)
    if not success:
        output['errors'].append("Error retrieving BMS warning info: " + data)

    print(json.dumps(output, indent=2))

else:  #BMS not connected
    output['errors'].append("BMS not connected")
    print(json.dumps(output, indent=2))
    bms, bms_connected = bms_connect()
