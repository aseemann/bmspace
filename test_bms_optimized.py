#!/usr/bin/env python3
import sys
import json
from bms_optimized import BmsController

def test_bms_controller():
    """Test the BmsController class with a mock serial port"""
    print("Testing BmsController class...")

    # Use the first command line argument as the serial port
    # or use a default value for testing
    serial_port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

    # Create a BmsController instance
    bms_controller = BmsController(serial_port, debug_level=1)

    # Try to connect (this will likely fail in a test environment without actual hardware)
    connected = bms_controller.connect()

    # Print connection status
    print(f"Connection status: {'Connected' if connected else 'Not connected'}")

    # Even if not connected, we can test the output structure
    print("Output structure:")
    print(json.dumps(bms_controller.output, indent=2))

    # Close the connection
    bms_controller.close()
    print("Connection closed.")

    print("Test completed.")

if __name__ == "__main__":
    test_bms_controller()
