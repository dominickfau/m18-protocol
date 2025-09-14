from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta, UTC
import time
import struct
import code
import argparse
import re

from serial.tools import list_ports
import requests
import serial




class DataType(Enum):
    "Data types for battery data fields."

    UINT = "uint"
    "Unsigned integer"
    DATE = "date"
    "UNIX time (seconds from 1 Jan 1970)"
    ASCII = "ascii"
    "Ascii string"
    SN = "sn"
    "Serial number (2 bytes battery type, 3 bytes serial)"
    ADC_T = "adc_t"
    "Analog-to-digital converter temperature (mV of thermistor)"
    DEC_T = "dec_t"
    "Decimal temperature (byte_1 + byte_2/255)"
    CELL_V = "cell_v"
    "Cell voltages (1: 3568, 2: 3567, 3:3570, etc)"
    HHMMSS = "hhmmss"
    "Time in HH:MM:SS format"


@dataclass
class DataField:
    "Class representing a battery data field."

    address: int
    length: int
    data_type: DataType
    description: str

    @property
    def addr_h(self) -> int:
        """Return the upper 8-bits of the address."""
        return (self.address >> 8) & 0xFF
    
    @property
    def addr_l(self) -> int:
        """Return the lower 8-bits of the address."""
        return self.address & 0xFF


def print_debug_bytes(data: bytearray) -> None:
    """Print a bytearray in hexadecimal format for debugging purposes."""
    data_print = " ".join(f"{byte:02X}" for byte in data)
    print(f"DEBUG: ", data_print)


def prompt_com_port_selection() -> str:
    """Prompt the user to select a serial port from the available options."""
    
    print("*** NO PORT SPECIFIED ***")
    print("Available serial ports (choose one that says USB somewhere):")
    ports = list_ports.comports()
    
    i = 1
    for p in ports:
        print(f"  {i}: {p.device} - {p.manufacturer} - {p.description}")
        i = i + 1
    
    port_id = 0
    while (port_id < 1) or (port_id >= i):
        user_port = input(f"Choose a port (1-{i-1}): ")
        try:
            port_id = int(user_port)
        except ValueError:
            print("Invalid input. Please enter a number")
        
    p = ports[port_id - 1]
    print(f"You selected \"{p.device} - {p.manufacturer} - {p.description}\"")
    print(f"In future, use \"m18.py --port {p.device}\" to avoid this menu")
    input("Press Enter to continue")
    
    return p.device



class M18:
    """Class to communicate with Milwaukee M18 battery chargers via serial port."""

    SYNC_BYTE     = 0xAA
    CAL_CMD       = 0x55
    CONF_CMD      = 0x60
    SNAP_CMD      = 0x61
    KEEPALIVE_CMD = 0x62

    CUTOFF_CURRENT = 300
    MAX_CURRENT = 6000

    ACC = 4
    
    PRINT_TX = False
    PRINT_RX = False
    
    # Used to temporarily disable then restore print_tx/rx state
    PRINT_TX_SAVE = False 
    PRINT_RX_SAVE = False

    # Serial port configuration
    BAUDRATE = 4800
    TIMEOUT = 0.8
    STOPBITS = 2

    def __init__(self, port: str) -> None:
        if port is None:
            port = prompt_com_port_selection()
            
        self.port = serial.Serial(port, baudrate=self.BAUDRATE, timeout=self.TIMEOUT, stopbits=self.STOPBITS)
        self.idle()
        
    def set_txrx_print(self, enable = True):
        """Enable or disable TX/RX printing."""
        self.PRINT_TX = enable
        self.PRINT_RX = enable
        
    def save_and_set_txrx(self, enable = True):
        """Save current TX/RX print state and set to 'enable'."""
        self.PRINT_TX_SAVE = self.PRINT_TX
        self.PRINT_RX_SAVE = self.PRINT_RX
        self.set_txrx_print(enable)
        
    def restore_txrx(self):
        """Restore TX/RX print state to what it was before the last save_and_set."""
        self.PRINT_TX = self.PRINT_TX_SAVE
        self.PRINT_RX = self.PRINT_RX_SAVE

    def calculate_checksum(self, payload: bytearray) -> int:
        """Calculate the checksum for a given bytearray."""
        checksum = 0
        for byte in payload:
            checksum += byte & 0xFFFF
        return checksum
    
    def add_checksum(self, lsb_command: bytearray) -> bytearray:
        """Add checksum to a command."""
        lsb_command += struct.pack(">H", self.calculate_checksum(lsb_command)) 
        return lsb_command
    
    def _send(self, message: bytearray) -> None:
        """Write a message to the serial port with bit-reversed bytes."""
        self.port.reset_input_buffer()
        debug_print = " ".join(f"{byte:02X}" for byte in message)
        msb = bytearray(self.reverse_bits(byte) for byte in message)
        if self.PRINT_TX:
            print(f"Sending:  {debug_print}")
        self.port.write(msb)

    def send_command(self, command: bytearray) -> None:
        """Send a command with checksum to the device."""
        self._send(self.add_checksum(command))

    def read_response(self, size: int) -> bytearray:
        """Read a response from the device."""
        msb_response = self.port.read(1)
        if not msb_response or len(msb_response) < 1: raise ValueError("Empty response")

        if self.reverse_bits(msb_response[0]) == 0x82:
            msb_response += self.port.read(1)
        else:
            msb_response += self.port.read(size-1)

        lsb_response = bytearray(self.reverse_bits(byte) for byte in msb_response)
        debug_print = " ".join(f"{byte:02X}" for byte in lsb_response)
        if self.PRINT_RX:
            print(f"Received: {debug_print}")

        return lsb_response