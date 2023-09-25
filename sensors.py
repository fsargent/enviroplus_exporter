import contextlib
import logging
import os
from typing import Optional

import aqi
import board
import numpy
from adafruit_lc709203f import LC709203F, PackSize
from bme280 import BME280
from dotenv import load_dotenv
from enviroplus import gas
from pms5003 import PMS5003
from pms5003 import ChecksumMismatchError as pmsChecksumMismatchError
from pms5003 import ReadTimeoutError as pmsReadTimeoutError
from pms5003 import SerialTimeoutError as pmsSerialTimeoutError
from prometheus_client import Gauge, Histogram
from smbus import SMBus

try:
    # Transitional fix for breaking change in LTR559
    from ltr559 import LTR559

    ltr559 = LTR559()
except ImportError:
    import ltr559

from aqi_utilities import get_external_AQI

DEBUG = os.getenv("DEBUG", "false") == "true"

bus = SMBus(1)
bme280 = BME280(i2c_dev=bus)
pms5003 = PMS5003()


load_dotenv()
battery_sensor = None
with contextlib.suppress(ValueError):
    battery_sensor = LC709203F(board.I2C())


logging.basicConfig(
    format="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)

LATITUDE = os.getenv("LATITUDE", "")
LONGITUDE = os.getenv("LONGITUDE", "")
WAQI_API_KEY = os.getenv("WAQI_API_KEY", "")


# Pressure variables
pressure_vals = []
time_vals = []
num_vals = 1000
interval = 1
trend = "-"


TEMPERATURE = Gauge("temperature", "Temperature measured (*C)")
PRESSURE = Gauge("pressure", "Pressure measured (hPa)")
HUMIDITY = Gauge("humidity", "Relative humidity measured (%)")
OXIDISING = Gauge(
    "oxidising", "Mostly nitrogen dioxide but could include NO and Hydrogen (Ohms)"
)
REDUCING = Gauge(
    "reducing",
    "Mostly carbon monoxide but could include H2S, Ammonia, Ethanol, Hydrogen, Methane, Propane, Iso-butane (Ohms)",
)
NH3 = Gauge(
    "NH3",
    "mostly Ammonia but could also include Hydrogen, Ethanol, Propane, Iso-butane (Ohms)",
)
LUX = Gauge("lux", "current ambient light level (lux)")
PROXIMITY = Gauge(
    "proximity", "proximity, with larger numbers being closer proximity and vice versa"
)
PM1 = Gauge(
    "PM1",
    "Particulate Matter of diameter less than 1 micron. Measured in micrograms per cubic metre (ug/m3)",
)
PM25 = Gauge(
    "PM25",
    "Particulate Matter of diameter less than 2.5 microns. Measured in micrograms per cubic metre (ug/m3)",
)
PM10 = Gauge(
    "PM10",
    "Particulate Matter of diameter less than 10 microns. Measured in micrograms per cubic metre (ug/m3)",
)
AQI = Gauge("AQI", "EPA Air Quality Measurement")
CPU_TEMPERATURE = Gauge("cpu_temperature", "CPU temperature measured (*C)")
BATTERY_VOLTAGE = Gauge("battery_voltage", "Voltage of the battery (Volts)")
BATTERY_PERCENTAGE = Gauge(
    "battery_percentage", "Percentage of the battery remaining (%)"
)

OXIDISING_HIST = Histogram(
    "oxidising_measurements",
    "Histogram of oxidising measurements",
    buckets=(
        0,
        10000,
        15000,
        20000,
        25000,
        30000,
        35000,
        40000,
        45000,
        50000,
        55000,
        60000,
        65000,
        70000,
        75000,
        80000,
        85000,
        90000,
        100000,
    ),
)
REDUCING_HIST = Histogram(
    "reducing_measurements",
    "Histogram of reducing measurements",
    buckets=(
        0,
        100000,
        200000,
        300000,
        400000,
        500000,
        600000,
        700000,
        800000,
        900000,
        1000000,
        1100000,
        1200000,
        1300000,
        1400000,
        1500000,
    ),
)
NH3_HIST = Histogram(
    "nh3_measurements",
    "Histogram of nh3 measurements",
    buckets=(
        0,
        10000,
        110000,
        210000,
        310000,
        410000,
        510000,
        610000,
        710000,
        810000,
        910000,
        1010000,
        1110000,
        1210000,
        1310000,
        1410000,
        1510000,
        1610000,
        1710000,
        1810000,
        1910000,
        2000000,
    ),
)

PM1_HIST = Histogram(
    "pm1_measurements",
    "Histogram of Particulate Matter of diameter less than 1 micron measurements",
    buckets=(
        0,
        5,
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        55,
        60,
        65,
        70,
        75,
        80,
        85,
        90,
        95,
        100,
    ),
)
PM25_HIST = Histogram(
    "pm25_measurements",
    "Histogram of Particulate Matter of diameter less than 2.5 micron measurements",
    buckets=(
        0,
        5,
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        55,
        60,
        65,
        70,
        75,
        80,
        85,
        90,
        95,
        100,
    ),
)
PM10_HIST = Histogram(
    "pm10_measurements",
    "Histogram of Particulate Matter of diameter less than 10 micron measurements",
    buckets=(
        0,
        5,
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        55,
        60,
        65,
        70,
        75,
        80,
        85,
        90,
        95,
        100,
    ),
)
AQI_HIST = Histogram(
    "aqi_measurements",
    "Histogram of EPA AQI measurements",
    buckets=(
        0,
        5,
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        55,
        60,
        65,
        70,
        75,
        80,
        85,
        90,
        95,
        100,
    ),
)


def get_pressure():
    """Get pressure from the weather sensor."""
    pressure = bme280.get_pressure()
    PRESSURE.set(pressure)


def get_humidity(humidity_compensation=None):
    """Get humidity from the weather sensor."""
    # Increase the humidity_compensation to increase the humidity.
    # Decrease it to decrease the humidity.
    humidity = bme280.get_humidity()

    if humidity_compensation:
        humidity = humidity + humidity_compensation

    return humidity


def get_gas():
    """Get all gas readings."""
    try:
        readings = gas.read_all()
    except (OSError, ValueError) as exception:
        logging.warning(f"Failed to read gas sensor with error: {exception}")
    else:
        OXIDISING.set(readings.oxidising)
        OXIDISING_HIST.observe(readings.oxidising)

        REDUCING.set(readings.reducing)
        REDUCING_HIST.observe(readings.reducing)

        NH3.set(readings.nh3)
        NH3_HIST.observe(readings.nh3)


def get_light():
    """Get all light readings."""
    try:
        lux = ltr559.get_lux()
        prox = ltr559.get_proximity()
    except OSError as exception:
        logging.warning(f"Failed to read light sensor with error: {exception}")
    else:
        LUX.set(lux)
        PROXIMITY.set(prox)


def read_pms_data() -> Optional[dict]:
    """Attempt to read data from PMS5003 and return it."""
    try:
        return pms5003.read()
    except (pmsReadTimeoutError, pmsSerialTimeoutError, pmsChecksumMismatchError):
        logging.warning("Failed to read PMS5003")
        return None


def calculate_aqi(pm25: float, pm10: float) -> float:
    """Calculate AQI based on PM2.5 and PM10 values."""
    return aqi.to_aqi(
        [
            (aqi.POLLUTANT_PM25, pm25),
            (aqi.POLLUTANT_PM10, pm10),
        ]
    )


def get_particulates() -> dict[str, float]:
    """Get the particulate matter readings."""
    pms_data = read_pms_data()

    if not pms_data:
        return {}

    pm1 = pms_data.pm_ug_per_m3(1.0)
    pm25 = pms_data.pm_ug_per_m3(2.5)
    pm10 = pms_data.pm_ug_per_m3(10)
    myaqi = calculate_aqi(pm25, pm10)

    PM1.set(pm1)
    PM25.set(pm25)
    PM10.set(pm10)

    PM1_HIST.observe(pm1)
    PM25_HIST.observe(pm25 - pm1)
    PM10_HIST.observe(pm10 - pm25)

    AQI.set(myaqi)
    AQI_HIST.observe(float(myaqi))

    return {"PM1": pm1, "PM25": pm25, "PM10": pm10, "myaqi": myaqi}


def get_battery():
    """Get the battery voltage and percentage left."""

    if not battery_sensor:
        return None, None
    logging.debug("## LC709203F battery monitor ##")
    try:
        logging.debug(f"Sensor IC version: {hex(battery_sensor.ic_version)}")
        # Set the battery pack size to 3000 mAh
        battery_sensor.pack_size = PackSize.MAH3000
        battery_sensor.init_RSOC()
        logging.debug(f"Battery size: {PackSize.string[battery_sensor.pack_sizes]}")
    except RuntimeError as exception:
        logging.error(f"Failed to read sensor with error: {exception}")
        logging.info("Try setting the I2C clock speed to 10000Hz")
    try:
        voltage_reading = battery_sensor.cell_voltage
        percentage_reading = battery_sensor.cell_percent
        logging.debug(
            f"Battery: {battery_sensor.cell_voltage} Volts / {battery_sensor.cell_percent} %"
        )
        return voltage_reading, percentage_reading
    except (RuntimeError, OSError) as exception:
        logging.warning(f"Failed to read battery monitor with error: {exception}")
        return None, None


def analyse_pressure(pressure, t):
    global time_vals, pressure_vals, trend
    if len(pressure_vals) > num_vals:
        pressure_vals = pressure_vals[1:] + [pressure]
        time_vals = time_vals[1:] + [t]
        line = numpy.polyfit(time_vals, pressure_vals, 1, full=True)
        slope = line[0][0]
        intercept = line[0][1]
        variance = numpy.var(pressure_vals)
        residuals = numpy.var(
            [slope * x + intercept - y for x, y in zip(time_vals, pressure_vals)]
        )

        r_squared = 1 - residuals / variance
        change_per_hour = slope * 60 * 60
        mean_pressure = numpy.mean(pressure_vals)
        if r_squared > 0.5:
            if change_per_hour > 0.5:
                trend = ">"
            elif change_per_hour < -0.5:
                trend = "<"
            else:
                trend = "-"
            if trend != "-" and abs(change_per_hour) > 3:
                trend *= 2
    else:
        pressure_vals.append(pressure)
        time_vals.append(t)
        mean_pressure = numpy.mean(pressure_vals)
        change_per_hour = 0
        trend = "-"
    return mean_pressure, change_per_hour, trend


def describe_pressure(pressure):
    """Convert pressure into barometer-type description."""
    if pressure < 970:
        return "storm"
    elif 970 <= pressure < 990:
        return "rain"
    elif 990 <= pressure < 1010:
        return "change"
    elif 1010 <= pressure < 1030:
        return "good"
    else:
        return "dry"


def describe_humidity(humidity):
    """Convert relative humidity into good/bad description."""
    return "good" if 30 < humidity < 70 else "bad"


def describe_light(light):
    """Convert light level in lux to descriptive value."""
    if light < 50:
        return "dark"
    elif 50 <= light < 100:
        return "dim"
    elif 100 <= light < 500:
        return "light"
    else:
        return "bright"


class Temperature:
    def __init__(self, value: float):
        self._value = value

    def to_celsius(self) -> "Celsius":
        raise NotImplementedError

    def to_fahrenheit(self) -> "Fahrenheit":
        raise NotImplementedError

    def __str__(self):
        raise NotImplementedError

    def __repr__(self):
        raise NotImplementedError

    def __add__(self, other):
        if isinstance(other, Temperature):
            return Temperature(self._value + other._value)
        raise ValueError("Can't add Temperature with non-Temperature type")

    def __radd__(self, other):
        if isinstance(other, (int, float)):
            return Temperature(self._value + other)
        raise ValueError("Can't add Temperature with non-numeric type")

    def __truediv__(self, number: float) -> "Temperature":
        if isinstance(number, (int, float)):
            return Temperature(self._value / number)
        raise ValueError("Temperature can only be divided by a number")


class Celsius(Temperature):
    def to_celsius(self):
        return self

    def to_fahrenheit(self):
        return Fahrenheit(self._value * 9 / 5 + 32)

    def __str__(self):
        return f"{self._value}°C"

    def __repr__(self):
        return f"Celsius({self._value}°C)"


class Fahrenheit(Temperature):
    def to_celsius(self):
        return Celsius((self._value - 32) * 5 / 9)

    def to_fahrenheit(self):
        return self

    def __str__(self):
        return f"{self._value}°F"

    def __repr__(self):
        return f"Fahrenheit({self._value}°F)"


class TemperatureSensor:
    def __init__(self, factor=2.25, smoothing_count=5):
        self.factor = factor
        self.cpu_temps = [self.get_cpu_temperature()] * smoothing_count
        self.bme280 = self._initialize_bme280()

    @staticmethod
    def _initialize_bme280():
        bus = SMBus(1)
        return BME280(i2c_dev=bus)

    @staticmethod
    def get_cpu_temperature() -> float:
        """Get the CPU temperature."""
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = int(f.read()) / 1000.0
            return temp

    def get_compensated_temperature(self):
        """Compensate the BME280 temperature reading with the CPU temperature."""
        cpu_temp = self.get_cpu_temperature()

        # Smooth out with some averaging to decrease jitter
        self.cpu_temps = self.cpu_temps[1:] + [cpu_temp]
        avg_cpu_temp = sum(self.cpu_temps) / float(len(self.cpu_temps))

        raw_temp = self.bme280.get_temperature()
        temperature = raw_temp - ((avg_cpu_temp - raw_temp) / self.factor)

        return temperature


# def get_current_temperature(cpu_temps) -> tuple[float, str, str]:
#     """Calculate the corrected temperature based on the CPU temperature and the temperature collected by the TEMPERATURE sensor.
#     The corrected temperature is adjusted by subtracting the difference between the average CPU temperature and the temperature collected by the TEMPERATURE sensor, divided by the factor.
#     If the time elapsed is greater than 30 seconds, the minimum and maximum temperatures are updated accordingly.
#     The temperature is then converted to Fahrenheit and displayed on an image.
#     The range of temperatures is also calculated and returned along with the corrected temperature, minimum temperature, and maximum temperature.

#     Returns:
#     -------
#         corrected_temperature (float): The corrected temperature in Celsius.
#         min_temp (float): The minimum temperature in Celsius.
#         max_temp (float): The maximum temperature in Celsius.

#     Example:
#     -------
#         ```python
#         corrected_temperature, min_temp, max_temp = corrected_temperature()
#         print(f"Corrected temperature: {corrected_temperature}°C")
#         print(f"Temperature range: {min_temp}°C - {max_temp}°C")
#         ```
#     """

#     min_temp = None
#     max_temp = None

#     factor = 2.25

#     # Corrected temperature
#     avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
#     corr_temperature = TEMPERATURE.collect()[0].samples[0].value - (
#         (avg_cpu_temp - TEMPERATURE.collect()[0].samples[0].value) / factor
#     )

#     # if time_elapsed > 30:
#     if min_temp is None or max_temp is None:
#         min_temp = corr_temperature
#         max_temp = corr_temperature

#     elif corr_temperature < min_temp:
#         min_temp = corr_temperature
#     elif corr_temperature > max_temp:
#         max_temp = corr_temperature
#     temp_string = f"{(corr_temperature*1.8)+32:.0f}°F"

#     if min_temp is not None and max_temp is not None:
#         range_string = f"{(min_temp*1.8)+32:.0f}-{(max_temp*1.8)+32:.0f}"
#     else:
#         range_string = "------"
#     return corr_temperature, temp_string, range_string


# def display_temperature_range(temperature, min_temp, max_temp):
#     if min_temp is not None and max_temp is not None:
#         range_string = f"{(min_temp*1.8)+32:.0f}-{(max_temp*1.8)+32:.0f}"
#     else:
#         range_string = "------"
#     return range_string


def correct_humidity(humidity, temperature, corr_temperature):
    dewpoint = temperature - ((100 - humidity) / 5)
    corr_humidity = 100 - (5 * (corr_temperature - dewpoint))
    return min(100, corr_humidity)


def poll_sensors():
    temperature = TemperatureSensor()

    voltage_reading, percentage_reading = get_battery()
    BATTERY_VOLTAGE.set(voltage_reading or 0)
    BATTERY_PERCENTAGE.set(percentage_reading or 0)

    CPU_TEMPERATURE.set(temperature.get_cpu_temperature())
    TEMPERATURE.set(temperature.get_compensated_temperature())

    HUMIDITY.set(get_humidity())
    get_gas()
    get_light()
    get_particulates()
    get_pressure()
    get_pressure()


def collect_all_data() -> dict[str, float]:
    """Collect all the data currently set."""
    poll_sensors()

    sensor_data = {
        "temperature": TEMPERATURE.collect()[0].samples[0].value,
        "humidity": HUMIDITY.collect()[0].samples[0].value,
        "pressure": PRESSURE.collect()[0].samples[0].value,
        "oxidising": OXIDISING.collect()[0].samples[0].value,
        "reducing": REDUCING.collect()[0].samples[0].value,
        "nh3": NH3.collect()[0].samples[0].value,
        "lux": LUX.collect()[0].samples[0].value,
        "proximity": PROXIMITY.collect()[0].samples[0].value,
        "pm1": PM1.collect()[0].samples[0].value,
        "pm25": PM25.collect()[0].samples[0].value,
        "pm10": PM10.collect()[0].samples[0].value,
        "cpu_temperature": CPU_TEMPERATURE.collect()[0].samples[0].value,
        "battery_voltage": BATTERY_VOLTAGE.collect()[0].samples[0].value,
        "battery_percentage": BATTERY_PERCENTAGE.collect()[0].samples[0].value,
        "aqi": AQI.collect()[0].samples[0].value,
        "internal_aqi": int(
            aqi.to_aqi(
                [
                    (aqi.POLLUTANT_PM25, PM25.collect()[0].samples[0].value),
                    (aqi.POLLUTANT_PM10, PM10.collect()[0].samples[0].value),
                ]
            )
        ),
        "external_aqi": get_external_AQI(LATITUDE, LONGITUDE, WAQI_API_KEY),
    }

    # sensor_data["corr_temperature"] = get_current_temperature()

    # sensor_data["corr_humidity"] = correct_humidity(
    #     sensor_data["humidity"],
    #     sensor_data["temperature"],
    #     sensor_data["corr_temperature"],
    # )

    return sensor_data
