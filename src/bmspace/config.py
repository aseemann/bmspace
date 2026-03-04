"""Configuration loading and dataclass for bmspace."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import yaml


@dataclass
class Config:
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_ha_discovery: bool
    mqtt_ha_discovery_topic: str
    mqtt_base_topic: str
    connection_type: str   # "Serial" | "IP"
    bms_ip: str
    bms_port: int
    bms_serial: str
    scan_interval: int
    debug_output: int


def load_config(
    options_path: str = "/data/options.json",
    yaml_path: str = "config.yaml",
) -> Config:
    """
    Load configuration from the first file that exists.

    Priority: ``options_path`` (Home Assistant add-on) → ``yaml_path``.
    Raises ``FileNotFoundError`` when neither is found.
    """
    raw: dict = {}

    if os.path.exists(options_path):
        with open(options_path) as fh:
            raw = json.load(fh)

    elif os.path.exists(yaml_path):
        with open(yaml_path) as fh:
            raw = yaml.load(fh, Loader=yaml.FullLoader)["options"]

    else:
        raise FileNotFoundError(
            f"No config file found (tried {options_path!r} and {yaml_path!r})"
        )

    return Config(
        mqtt_host=raw["mqtt_host"],
        mqtt_port=int(raw["mqtt_port"]),
        mqtt_user=raw["mqtt_user"],
        mqtt_password=raw["mqtt_password"],
        mqtt_ha_discovery=bool(raw["mqtt_ha_discovery"]),
        mqtt_ha_discovery_topic=raw["mqtt_ha_discovery_topic"],
        mqtt_base_topic=raw["mqtt_base_topic"],
        connection_type=raw["connection_type"],
        bms_ip=raw.get("bms_ip", ""),
        bms_port=int(raw.get("bms_port", 5000)),
        bms_serial=raw.get("bms_serial", "/dev/ttyUSB0"),
        scan_interval=int(raw["scan_interval"]),
        debug_output=int(raw.get("debug_output", 0)),
    )
