"""
Application entry point and main polling loop.

Responsibilities:
- Load configuration
- Manage BMS transport reconnection
- Manage MQTT reconnection
- Orchestrate: read BMS data → publish to MQTT
- Trigger HA discovery once and re-publish every hour
"""
from __future__ import annotations

import atexit
import logging
import time

from .bms import get_analog_data, get_pack_capacity, get_serial, get_version, get_warn_info
from .config import load_config
from .mqtt_client import MqttPublisher
from .transport import TransportError, create_transport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_DISCOVERY_INTERVAL_SECS = 3600


def main() -> None:
    config = load_config()

    if config.debug_output > 0:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("Starting bmspace (connection_type=%s)", config.connection_type)

    publisher = MqttPublisher(config)
    publisher.connect()
    time.sleep(2)  # give the MQTT loop a moment to establish the connection

    atexit.register(publisher.disconnect)

    transport = create_transport(config)

    while True:
        # ----------------------------------------------------------------
        # (Re)connect to BMS
        # ----------------------------------------------------------------
        try:
            transport.connect()
        except (OSError, TransportError) as exc:
            logger.error("BMS connect failed: %s – retrying in 5 s", exc)
            publisher.publish_availability(online=False)
            time.sleep(5)
            continue

        # ----------------------------------------------------------------
        # Read one-time BMS metadata
        # ----------------------------------------------------------------
        try:
            bms_version = get_version(transport)
            logger.info("BMS version: %s", bms_version)

            bms_sn, pack_sn = get_serial(transport)
            logger.info("BMS SN: %s  Pack SN: %s", bms_sn, pack_sn)

            publisher.publish_bms_info(bms_version, bms_sn, pack_sn)
        except RuntimeError as exc:
            logger.error("Failed to read BMS metadata: %s – retrying in 5 s", exc)
            transport.disconnect()
            time.sleep(5)
            continue

        packs = 0
        cells = 13
        temps = 6
        ha_published = False
        discovery_timer = 0

        # ----------------------------------------------------------------
        # Polling loop – runs until a BMS read error forces a reconnect
        # ----------------------------------------------------------------
        while True:
            if not publisher.is_connected:
                logger.warning("MQTT disconnected – reconnecting")
                publisher.reconnect()
                time.sleep(5)
                continue

            try:
                # Analog data (cell voltages, temperatures, currents …)
                analog_list = get_analog_data(transport)
                packs = len(analog_list)
                for pack in analog_list:
                    publisher.publish_analog_data(pack)
                    cells = len(pack.cells)
                    temps = len(pack.temps)
                time.sleep(config.scan_interval / 3)

                # Overall pack capacity
                cap = get_pack_capacity(transport)
                publisher.publish_pack_capacity(cap)
                time.sleep(config.scan_interval / 3)

                # Warning / protection / balancing states
                warn_list = get_warn_info(transport, packs)
                for warn in warn_list:
                    publisher.publish_warn_info(warn)
                time.sleep(config.scan_interval / 3)

                # HA discovery – publish once at startup, then every hour
                if not ha_published or (
                    discovery_timer * config.scan_interval >= _DISCOVERY_INTERVAL_SECS
                ):
                    publisher.publish_ha_discovery(
                        bms_sn, bms_version, packs, cells, temps
                    )
                    ha_published = True
                    discovery_timer = 0

                discovery_timer += 1
                publisher.publish_availability(online=True)

            except RuntimeError as exc:
                logger.error("BMS read error: %s – reconnecting", exc)
                transport.disconnect()
                publisher.publish_availability(online=False)
                time.sleep(5)
                break  # back to outer loop to reconnect


if __name__ == "__main__":
    main()
