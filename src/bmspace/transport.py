"""
Transport abstraction for communicating with the BMS.

Two concrete implementations are provided:
- ``SerialTransport`` – RS232 via pyserial
- ``TcpTransport``    – TCP/IP socket

Both expose the same ``connect / disconnect / send / receive`` interface,
so the BMS command layer is transport-agnostic.
"""
from __future__ import annotations

import logging
import socket
import time
from typing import Protocol

import serial

from .config import Config

logger = logging.getLogger(__name__)

# SOI byte value used to detect the start of a valid frame
_SOI_BYTE = b"\x7e"


class TransportError(OSError):
    """Raised when a transport-level operation fails."""


class Transport(Protocol):
    """Structural protocol – both transports satisfy this interface."""

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def send(self, data: bytes) -> None: ...
    def receive(self) -> bytes: ...

    @property
    def is_connected(self) -> bool: ...


class SerialTransport:
    """RS232 / USB serial transport."""

    def __init__(self, port: str, timeout: float = 1.0) -> None:
        self._port = port
        self._timeout = timeout
        self._conn: serial.Serial | None = None

    def connect(self) -> None:
        logger.info("Connecting to serial port %s", self._port)
        self._conn = serial.Serial(self._port, timeout=self._timeout)
        logger.info("Serial port connected")

    def disconnect(self) -> None:
        if self._conn and self._conn.is_open:
            self._conn.close()
        self._conn = None

    def send(self, data: bytes) -> None:
        if not self._conn:
            raise TransportError("Serial port not connected")
        self._conn.write(data)
        time.sleep(0.25)

    def receive(self) -> bytes:
        if not self._conn:
            raise TransportError("Serial port not connected")
        return self._conn.readline()

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and self._conn.is_open


class TcpTransport:
    """TCP/IP socket transport."""

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._conn: socket.socket | None = None

    def connect(self) -> None:
        logger.info("Connecting to %s:%d", self._host, self._port)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self._timeout)
        s.connect((self._host, self._port))
        self._conn = s
        logger.info("TCP socket connected")

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None

    def send(self, data: bytes) -> None:
        if not self._conn:
            raise TransportError("TCP socket not connected")
        self._conn.send(data)
        time.sleep(0.25)

    def receive(self) -> bytes:
        if not self._conn:
            raise TransportError("TCP socket not connected")
        raw = self._conn.recv(4096)
        # The BMS may send multiple responses in one TCP segment.
        # Pick the frame that starts with the SOI byte.
        frames = raw.split(b"\r")
        for frame in frames:
            if frame and frame[0:1] == _SOI_BYTE:
                return frame + b"\r"
        return raw  # fall-back: return whatever arrived

    @property
    def is_connected(self) -> bool:
        return self._conn is not None


def create_transport(config: Config) -> SerialTransport | TcpTransport:
    """Factory: return the correct transport based on ``config.connection_type``."""
    if config.connection_type == "Serial":
        return SerialTransport(config.bms_serial)
    return TcpTransport(config.bms_ip, config.bms_port)
