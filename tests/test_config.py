"""Tests for src/bmspace/config.py"""
import json
import os
import tempfile

import pytest
import yaml

from bmspace.config import Config, load_config


MINIMAL_OPTIONS = {
    "mqtt_host": "192.168.1.10",
    "mqtt_port": 1883,
    "mqtt_user": "user",
    "mqtt_password": "secret",
    "mqtt_ha_discovery": True,
    "mqtt_ha_discovery_topic": "homeassistant",
    "mqtt_base_topic": "bmspace",
    "connection_type": "IP",
    "bms_ip": "192.168.1.20",
    "bms_port": 5000,
    "bms_serial": "/dev/ttyUSB0",
    "scan_interval": 5,
    "debug_output": 0,
}


def _write_json(path: str, data: dict) -> None:
    with open(path, "w") as fh:
        json.dump(data, fh)


def _write_yaml(path: str, options: dict) -> None:
    with open(path, "w") as fh:
        yaml.dump({"options": options}, fh)


class TestLoadConfigFromJson:
    def test_loads_all_fields(self, tmp_path):
        p = tmp_path / "options.json"
        _write_json(str(p), MINIMAL_OPTIONS)
        cfg = load_config(options_path=str(p), yaml_path="/nonexistent")
        assert cfg.mqtt_host == "192.168.1.10"
        assert cfg.mqtt_port == 1883
        assert cfg.mqtt_user == "user"
        assert cfg.mqtt_password == "secret"
        assert cfg.mqtt_ha_discovery is True
        assert cfg.mqtt_ha_discovery_topic == "homeassistant"
        assert cfg.mqtt_base_topic == "bmspace"
        assert cfg.connection_type == "IP"
        assert cfg.bms_ip == "192.168.1.20"
        assert cfg.bms_port == 5000
        assert cfg.bms_serial == "/dev/ttyUSB0"
        assert cfg.scan_interval == 5
        assert cfg.debug_output == 0

    def test_returns_config_dataclass(self, tmp_path):
        p = tmp_path / "options.json"
        _write_json(str(p), MINIMAL_OPTIONS)
        cfg = load_config(options_path=str(p), yaml_path="/nonexistent")
        assert isinstance(cfg, Config)

    def test_mqtt_port_coerced_to_int(self, tmp_path):
        p = tmp_path / "options.json"
        opts = dict(MINIMAL_OPTIONS, mqtt_port="1883")
        _write_json(str(p), opts)
        cfg = load_config(options_path=str(p), yaml_path="/nonexistent")
        assert isinstance(cfg.mqtt_port, int)
        assert cfg.mqtt_port == 1883

    def test_debug_output_coerced_to_int(self, tmp_path):
        p = tmp_path / "options.json"
        opts = dict(MINIMAL_OPTIONS, debug_output="2")
        _write_json(str(p), opts)
        cfg = load_config(options_path=str(p), yaml_path="/nonexistent")
        assert isinstance(cfg.debug_output, int)
        assert cfg.debug_output == 2


class TestLoadConfigFromYaml:
    def test_loads_from_yaml_when_json_missing(self, tmp_path):
        p = tmp_path / "config.yaml"
        _write_yaml(str(p), MINIMAL_OPTIONS)
        cfg = load_config(options_path="/nonexistent", yaml_path=str(p))
        assert cfg.mqtt_host == "192.168.1.10"
        assert cfg.bms_ip == "192.168.1.20"

    def test_returns_config_dataclass(self, tmp_path):
        p = tmp_path / "config.yaml"
        _write_yaml(str(p), MINIMAL_OPTIONS)
        cfg = load_config(options_path="/nonexistent", yaml_path=str(p))
        assert isinstance(cfg, Config)


class TestLoadConfigPriority:
    def test_json_takes_priority_over_yaml(self, tmp_path):
        json_path = tmp_path / "options.json"
        yaml_path = tmp_path / "config.yaml"

        _write_json(str(json_path), dict(MINIMAL_OPTIONS, mqtt_host="from-json"))
        _write_yaml(str(yaml_path), dict(MINIMAL_OPTIONS, mqtt_host="from-yaml"))

        cfg = load_config(options_path=str(json_path), yaml_path=str(yaml_path))
        assert cfg.mqtt_host == "from-json"


class TestLoadConfigMissing:
    def test_raises_when_no_file_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(
                options_path=str(tmp_path / "nope.json"),
                yaml_path=str(tmp_path / "nope.yaml"),
            )


class TestLoadConfigDefaults:
    def test_optional_fields_have_defaults(self, tmp_path):
        """Fields with defaults should not be required in the config file."""
        p = tmp_path / "options.json"
        opts = {k: v for k, v in MINIMAL_OPTIONS.items()
                if k not in ("bms_ip", "bms_port", "bms_serial", "debug_output")}
        _write_json(str(p), opts)
        cfg = load_config(options_path=str(p), yaml_path="/nonexistent")
        assert cfg.bms_ip == ""
        assert cfg.bms_port == 5000
        assert cfg.bms_serial == "/dev/ttyUSB0"
        assert cfg.debug_output == 0
