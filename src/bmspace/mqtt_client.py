"""
MQTT publishing and Home Assistant auto-discovery.

Uses the paho-mqtt 2.x callback API (CallbackAPIVersion.VERSION2).
"""
from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from .bms import PackAnalogData, PackCapacity, PackWarnInfo
from .config import Config

logger = logging.getLogger(__name__)


class MqttPublisher:
    """Wraps a paho MQTT client with topic-specific publish helpers."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._connected = False

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.username_pw_set(config.mqtt_user, config.mqtt_password)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        logger.info("MQTT connected (rc=%s)", reason_code)
        self._connected = True

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        logger.info("MQTT disconnected (rc=%s)", reason_code)
        self._connected = False

    def connect(self) -> None:
        self._client.connect(self._config.mqtt_host, self._config.mqtt_port, 60)
        self._client.loop_start()

    def disconnect(self) -> None:
        self.publish_availability(online=False)
        self._client.loop_stop()
        self._client.disconnect()

    def reconnect(self) -> None:
        self._client.loop_stop()
        self._client.connect(self._config.mqtt_host, self._config.mqtt_port, 60)
        self._client.loop_start()

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Generic publish helper
    # ------------------------------------------------------------------

    def _pub(self, subtopic: str, value: str | int | float, retain: bool = False) -> None:
        topic = f"{self._config.mqtt_base_topic}/{subtopic}"
        self._client.publish(topic, str(value), qos=0, retain=retain)

    # ------------------------------------------------------------------
    # Domain-specific publishers
    # ------------------------------------------------------------------

    def publish_availability(self, online: bool) -> None:
        self._pub("availability", "online" if online else "offline")

    def publish_bms_info(self, version: str, bms_sn: str, pack_sn: str) -> None:
        self._pub("bms_version", version)
        self._pub("bms_sn", bms_sn)
        self._pub("pack_sn", pack_sn)

    def publish_analog_data(self, pack: PackAnalogData) -> None:
        p = pack.pack_number
        for i, mv in enumerate(pack.cells, 1):
            self._pub(f"pack_{p}/v_cells/cell_{i}", mv)
        for i, temp in enumerate(pack.temps, 1):
            self._pub(f"pack_{p}/temps/temp_{i}", temp)
        self._pub(f"pack_{p}/i_pack",             pack.i_pack)
        self._pub(f"pack_{p}/v_pack",             pack.v_pack)
        self._pub(f"pack_{p}/i_remain_cap",       pack.i_remain_cap)
        self._pub(f"pack_{p}/i_full_cap",         pack.i_full_cap)
        self._pub(f"pack_{p}/i_design_cap",       pack.i_design_cap)
        self._pub(f"pack_{p}/soc",                pack.soc)
        self._pub(f"pack_{p}/soh",                pack.soh)
        self._pub(f"pack_{p}/cycles",             pack.cycles)
        self._pub(f"pack_{p}/cells_max_diff_calc", pack.cells_max_diff)

    def publish_pack_capacity(self, cap: PackCapacity) -> None:
        self._pub("pack_remain_cap",  cap.remain_cap)
        self._pub("pack_full_cap",    cap.full_cap)
        self._pub("pack_design_cap",  cap.design_cap)
        self._pub("pack_soc",         cap.soc)
        self._pub("pack_soh",         cap.soh)

    def publish_warn_info(self, warn: PackWarnInfo) -> None:
        p = warn.pack_number
        self._pub(f"pack_{p}/warnings",               warn.warnings)
        self._pub(f"pack_{p}/balancing1",             warn.balancing1)
        self._pub(f"pack_{p}/balancing2",             warn.balancing2)
        self._pub(f"pack_{p}/prot_short_circuit",     warn.prot_short_circuit)
        self._pub(f"pack_{p}/prot_discharge_current", warn.prot_discharge_current)
        self._pub(f"pack_{p}/prot_charge_current",    warn.prot_charge_current)
        self._pub(f"pack_{p}/fully",                  warn.fully)
        self._pub(f"pack_{p}/current_limit",          warn.current_limit)
        self._pub(f"pack_{p}/charge_fet",             warn.charge_fet)
        self._pub(f"pack_{p}/discharge_fet",          warn.discharge_fet)
        self._pub(f"pack_{p}/pack_indicate",          warn.pack_indicate)
        self._pub(f"pack_{p}/reverse",                warn.reverse)
        self._pub(f"pack_{p}/ac_in",                  warn.ac_in)
        self._pub(f"pack_{p}/heart",                  warn.heart)

    # ------------------------------------------------------------------
    # Home Assistant MQTT auto-discovery
    # ------------------------------------------------------------------

    def publish_ha_discovery(
        self,
        bms_sn: str,
        bms_version: str,
        packs: int,
        cells: int,
        temps: int,
    ) -> None:
        if not self._config.mqtt_ha_discovery:
            logger.info("HA discovery disabled")
            return

        logger.info("Publishing HA discovery payloads …")

        base_topic  = self._config.mqtt_base_topic
        disc_prefix = self._config.mqtt_ha_discovery_topic

        device = {
            "manufacturer": "BMS Pace",
            "model": "AM-x",
            "identifiers": f"bmspace_{bms_sn}",
            "name": "Generic Lithium",
            "sw_version": bms_version,
        }

        def _pub_entity(
            component: str,
            name: str,
            unique_suffix: str,
            state_subtopic: str,
            unit: str | None = None,
            extra: dict | None = None,
        ) -> None:
            payload: dict = {
                "availability_topic": f"{base_topic}/availability",
                "device": device,
                "name": name,
                "unique_id": f"bmspace_{bms_sn}_{unique_suffix}",
                "state_topic": f"{base_topic}/{state_subtopic}",
            }
            if unit is not None:
                payload["unit_of_measurement"] = unit
            if extra:
                payload.update(extra)
            slug = name.replace(" ", "_")
            self._client.publish(
                f"{disc_prefix}/{component}/BMS-{bms_sn}/{slug}/config",
                json.dumps(payload),
                qos=0,
                retain=True,
            )

        binary_extra = {"payload_on": "1", "payload_off": "0"}

        for p in range(1, packs + 1):
            for i in range(1, cells + 1):
                _pub_entity("sensor", f"Pack {p} Cell {i} Voltage",
                            f"pack_{p}_v_cell_{i}", f"pack_{p}/v_cells/cell_{i}", "mV")
            for i in range(1, temps + 1):
                _pub_entity("sensor", f"Pack {p} Temperature {i}",
                            f"pack_{p}_temp_{i}", f"pack_{p}/temps/temp_{i}", "°C")

            _pub_entity("sensor", f"Pack {p} Current",
                        f"pack_{p}_i_pack",        f"pack_{p}/i_pack",        "A")
            _pub_entity("sensor", f"Pack {p} Voltage",
                        f"pack_{p}_v_pack",        f"pack_{p}/v_pack",        "V")
            _pub_entity("sensor", f"Pack {p} Remaining Capacity",
                        f"pack_{p}_i_remain_cap",  f"pack_{p}/i_remain_cap",  "mAh")
            _pub_entity("sensor", f"Pack {p} State of Charge",
                        f"pack_{p}_soc",            f"pack_{p}/soc",           "%")
            _pub_entity("sensor", f"Pack {p} State of Health",
                        f"pack_{p}_soh",            f"pack_{p}/soh",           "%")
            _pub_entity("sensor", f"Pack {p} Cycles",
                        f"pack_{p}_cycles",         f"pack_{p}/cycles",        "")
            _pub_entity("sensor", f"Pack {p} Full Capacity",
                        f"pack_{p}_i_full_cap",     f"pack_{p}/i_full_cap",    "mAh")
            _pub_entity("sensor", f"Pack {p} Design Capacity",
                        f"pack_{p}_i_design_cap",   f"pack_{p}/i_design_cap",  "mAh")
            _pub_entity("sensor", f"Pack {p} Cell Max Volt Diff",
                        f"pack_{p}_cells_max_diff_calc",
                        f"pack_{p}/cells_max_diff_calc", "mV")
            _pub_entity("sensor", f"Pack {p} Warnings",
                        f"pack_{p}_warnings",       f"pack_{p}/warnings")
            _pub_entity("sensor", f"Pack {p} Balancing1",
                        f"pack_{p}_balancing1",     f"pack_{p}/balancing1")
            _pub_entity("sensor", f"Pack {p} Balancing2",
                        f"pack_{p}_balancing2",     f"pack_{p}/balancing2")

            for name, suffix, subtopic in [
                ("Protection Short Circuit",     "prot_short_circuit",     "prot_short_circuit"),
                ("Protection Discharge Current", "prot_discharge_current", "prot_discharge_current"),
                ("Protection Charge Current",    "prot_charge_current",    "prot_charge_current"),
                ("Current Limit",                "current_limit",          "current_limit"),
                ("Charge FET",                   "charge_fet",             "charge_fet"),
                ("Discharge FET",                "discharge_fet",          "discharge_fet"),
                ("Pack Indicate",                "pack_indicate",          "pack_indicate"),
                ("Reverse",                      "reverse",                "reverse"),
                ("AC In",                        "ac_in",                  "ac_in"),
                ("Heart",                        "heart",                  "heart"),
            ]:
                _pub_entity("binary_sensor", f"Pack {p} {name}",
                            f"pack_{p}_{suffix}", f"pack_{p}/{subtopic}",
                            extra=binary_extra)

        # Aggregate pack-level sensors
        _pub_entity("sensor", "Pack Remaining Capacity",
                    "pack_i_remain_cap", "pack_remain_cap", "mAh")
        _pub_entity("sensor", "Pack Full Capacity",
                    "pack_i_full_cap",   "pack_full_cap",   "mAh")
        _pub_entity("sensor", "Pack Design Capacity",
                    "pack_i_design_cap", "pack_design_cap", "mAh")
        _pub_entity("sensor", "Pack State of Charge",
                    "pack_soc",          "pack_soc",         "%")
        _pub_entity("sensor", "Pack State of Health",
                    "pack_soh",          "pack_soh",         "%")
