"""File definitions from the Huawei inverter"""
from typing import Optional
from datetime import datetime
from enum import IntEnum
import struct
from dataclasses import dataclass

from huawei_solar.exceptions import HuaweiSolarException

from huawei_solar.utils import get_local_timezone


OPTIMIZER_ALARM_CODES = {
    0b0000_0000_0000_0001: "Input Overvoltage",
    0b0000_0000_0000_0010: "Input Undervoltage",
    0b0000_0000_0000_1000: "Output Overvoltage",
    0b0000_0000_0001_0000: "Overtemperature",
    0b0000_0000_0010_0000: "Output Short Circuit",
    0b0000_0000_0100_0000: "EEPROM Fault",
    0b0000_0000_1000_0000: "Internal Hardware Fault",
    0b0000_0001_0000_0000: "Abnormal Voltage To Ground",
    0b0000_0010_0000_0000: "Power-off due to heartbeat timeout",
    0b0000_0100_0000_0000: "Fast shutdown",
    0b0000_1000_0000_0000: "Request Escape Alarm",
    0b0001_0000_0000_0000: "Version mismatch alarm",
    0b1000_0000_0000_0000: "Input overvoltage",
    0b0001_0000_0000_0000_0000: "Overtemperature",
    0b0010_0000_0000_0000_0000: "Output short circuit",
    0b0100_0000_0000_0000_0000: "Internal hardware fault",
    0b1000_0000_0000_0000_0000: "Version mismatch alarm",
    0b0001_0000_0000_0000_0000_0000: "Backfeed alarm",
    0b0010_0000_0000_0000_0000_0000: "Abnormal output voltage",
    0b0100_0000_0000_0000_0000_0000: "Upgrade failure",
    0b0100_0000_0000_0000_0000_0000_0000: "Display bit 16 to bit 30 alarms",
}


class OptimizerRunningStatus(IntEnum):
    """Optimizer Running Status"""

    OFFLINE = 0
    STANDBY = 1
    FAULTY = 3
    RUNNING = 4
    POWER_OFF = 12

    def __str__(self) -> str:
        return self.name.replace("_", " ").capitalize()


@dataclass(frozen=True)
class OptimizerRealTimeData:
    optimizer_address: int
    output_power: float  # W
    voltage_to_ground: float  # V
    alarm: list[str]
    output_voltage: float  # V
    output_current: float  # A
    input_voltage: float  # V
    input_current: float  # A
    temperature: float  # C
    running_status: OptimizerRunningStatus
    accumulated_energy_yield: float  # kWh


@dataclass(frozen=True)
class OptimizerHistoryRealTimeDataUnit:
    time: datetime
    optimizers: list[OptimizerRealTimeData]


class OptimizerRealTimeDataFile:

    FILE_TYPE = 0x44

    HEADER = "<4s8x"
    OPTIMIZER_DATA_UNIT = "<i4xhh"

    OPTIMIZER_DATA = "<3HI6HI"

    def __init__(self, file_data):

        self.data_units: list[OptimizerHistoryRealTimeDataUnit] = []

        offset = 0

        # Check if we have an empty file
        if len(file_data) < struct.calcsize(OptimizerRealTimeDataFile.HEADER):
            return

        self.file_version = struct.unpack_from(
            OptimizerRealTimeDataFile.HEADER, file_data, offset
        )
        offset += struct.calcsize(OptimizerRealTimeDataFile.HEADER)

        has_next_optimizer_data_unit = True
        while has_next_optimizer_data_unit:

            time, length, number_of_optimizers = struct.unpack_from(
                OptimizerRealTimeDataFile.OPTIMIZER_DATA_UNIT, file_data, offset
            )
            offset += struct.calcsize(OptimizerRealTimeDataFile.OPTIMIZER_DATA_UNIT)

            optimizers = []
            for _ in range(number_of_optimizers):
                (
                    optimizer_address,
                    output_power,
                    voltage_to_ground,
                    alarm,
                    output_voltage,
                    output_current,
                    input_voltage,
                    input_current,
                    temperature,
                    running_status,
                    accumulated_energy_yield,
                ) = struct.unpack_from(
                    OptimizerRealTimeDataFile.OPTIMIZER_DATA, file_data, offset
                )
                offset += struct.calcsize(OptimizerRealTimeDataFile.OPTIMIZER_DATA)

                alarms = []
                for bit, value in OPTIMIZER_ALARM_CODES.items():
                    if alarm & bit:
                        alarms.append(value)

                optimizers.append(
                    OptimizerRealTimeData(
                        optimizer_address,
                        output_power / 10,
                        voltage_to_ground / 10,
                        alarms,
                        output_voltage / 10,
                        output_current / 100,
                        input_voltage / 10,
                        input_current / 100,
                        temperature / 10,
                        OptimizerRunningStatus(running_status),
                        accumulated_energy_yield / 1000,
                    )
                )

            self.data_units.append(
                OptimizerHistoryRealTimeDataUnit(
                    datetime.fromtimestamp(time, tz=get_local_timezone()), optimizers
                )
            )

            has_next_optimizer_data_unit = offset < len(file_data)

    def __str__(self) -> str:
        return f"OptimizerHistoryDataFile(file_version=f{self.file_version}, data_units=f{self.data_units})"

    @staticmethod
    def query_within_timespan(start_time: int, end_time: int):

        # the values below were deduced from observing network traffic and reverse-engineering the app
        tag = 0x10
        value_length = 12

        reserved = 0
        return struct.pack(">BBIII", tag, value_length, start_time, end_time, reserved)


class OptimizerOnlineStatus(IntEnum):
    """Optimizer Running Status"""

    OFFLINE = 0
    ONLINE = 1
    DISCONNECTED = 2

    def __str__(self) -> str:
        return self.name.replace("_", " ").capitalize()


@dataclass(frozen=True)
class OptimizerSystemInformation:
    optimizer_address: int
    online_status: OptimizerOnlineStatus
    string_number: int
    position_in_current_string: Optional[
        int
    ]  # relative position connection starting point
    sn: str
    software_version: str
    alias: str
    model: str


class OptimizerSystemInformationDataFile:

    FILE_TYPE = 0x45

    HEADER = ">4sHH?3xH"
    OPTIMIZER_FEATURE_DATA = ">HHHH20s30s20s30s"

    def __init__(self, file_data):

        self.optimizers: list[OptimizerSystemInformation] = []

        offset = 0

        (
            self.file_version,
            feature_data_sequence_number,
            length,
            reserved,
            number_of_optimizers,
        ) = struct.unpack_from(
            OptimizerSystemInformationDataFile.HEADER, file_data, offset
        )
        offset += struct.calcsize(OptimizerSystemInformationDataFile.HEADER)

        if self.file_version != b"V102":
            raise HuaweiSolarException("Only V102 file format is supported.")

        for _ in range(number_of_optimizers):
            (
                optimizer_address,
                online_status,
                string_number,
                position_in_current_string,
                sn,
                software_version,
                alias,
                model,
            ) = struct.unpack_from(
                OptimizerSystemInformationDataFile.OPTIMIZER_FEATURE_DATA,
                file_data,
                offset,
            )
            offset += struct.calcsize(
                OptimizerSystemInformationDataFile.OPTIMIZER_FEATURE_DATA
            )

            self.optimizers.append(
                OptimizerSystemInformation(
                    optimizer_address,
                    OptimizerOnlineStatus(online_status),
                    string_number,
                    position_in_current_string
                    if position_in_current_string != 0xFFFF
                    else None,
                    sn.decode("ascii").rstrip("\x00"),
                    software_version.decode("ascii").rstrip("\x00"),
                    alias.decode("ascii").rstrip("\x00"),
                    model.decode("ascii").rstrip("\x00"),
                )
            )