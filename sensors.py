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

from aqi_utilities import get_external_AQI

try:
    # Transitional fix for breaking change in LTR559
    from ltr559 import LTR559

    ltr559 = LTR559()
except ImportError:
    import ltr559

# from aqi_utilities import get_external_AQI

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


class SensorMetrics:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SensorMetrics, cls).__new__(cls)
            cls._instance.init_metrics()

        return cls._instance

    def collect_all_data(self):
        """Return all the data currently set."""
        self.get_battery()
        self.get_gas()
        self.get_humidity()
        self.get_light()
        self.get_particulates()
        self.get_pressure()
        self.temperature.get_compensated_temperature()
        self.temperature.get_cpu_temperature()

        return self.latest_values

    def init_metrics(self):
        self.temperature = TemperatureSensor()

        self.latest_values = {
            "temperature": 0.0,
            "humidity": 0.0,
            "pressure": 0.0,
            "oxidising": 0.0,
            "reducing": 0.0,
            "nh3": 0.0,
            "lux": 0.0,
            "proximity": 0.0,
            "pm1": 0.0,
            "pm25": 0.0,
            "pm10": 0.0,
            "cpu_temperature": 0.0,
            "battery_voltage": 0.0,
            "battery_percentage": 0.0,
            "internal_aqi": int(
                aqi.to_aqi(
                    [
                        (aqi.POLLUTANT_PM25, 0),
                        (aqi.POLLUTANT_PM10, 0),
                    ]
                )
            ),
            "external_aqi": get_external_AQI(LATITUDE, LONGITUDE, WAQI_API_KEY),
        }

        self.TEMPERATURE = Gauge("temperature", "Temperature measured (*C)")
        self.PRESSURE = Gauge("pressure", "Pressure measured (hPa)")
        self.HUMIDITY = Gauge("humidity", "Relative humidity measured (%)")
        self.OXIDISING = Gauge(
            "oxidising",
            "Mostly nitrogen dioxide but could include NO and Hydrogen (Ohms)",
        )
        self.REDUCING = Gauge(
            "reducing",
            "Mostly carbon monoxide but could include H2S, Ammonia, Ethanol, Hydrogen, Methane, Propane, Iso-butane (Ohms)",
        )
        self.NH3 = Gauge(
            "NH3",
            "mostly Ammonia but could also include Hydrogen, Ethanol, Propane, Iso-butane (Ohms)",
        )
        self.LUX = Gauge("lux", "current ambient light level (lux)")
        self.PROXIMITY = Gauge(
            "proximity",
            "proximity, with larger numbers being closer proximity and vice versa",
        )
        self.PM1 = Gauge(
            "PM1",
            "Particulate Matter of diameter less than 1 micron. Measured in micrograms per cubic metre (ug/m3)",
        )
        self.PM25 = Gauge(
            "PM25",
            "Particulate Matter of diameter less than 2.5 microns. Measured in micrograms per cubic metre (ug/m3)",
        )
        self.PM10 = Gauge(
            "PM10",
            "Particulate Matter of diameter less than 10 microns. Measured in micrograms per cubic metre (ug/m3)",
        )
        self.AQI = Gauge("AQI", "EPA Air Quality Measurement")
        self.CPU_TEMPERATURE = Gauge("cpu_temperature", "CPU temperature measured (*C)")
        self.BATTERY_VOLTAGE = Gauge(
            "battery_voltage", "Voltage of the battery (Volts)"
        )
        self.BATTERY_PERCENTAGE = Gauge(
            "battery_percentage", "Percentage of the battery remaining (%)"
        )

        self.OXIDISING_HIST = Histogram(
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
        self.REDUCING_HIST = Histogram(
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
        self.NH3_HIST = Histogram(
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

        self.PM1_HIST = Histogram(
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
        self.PM25_HIST = Histogram(
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
        self.PM10_HIST = Histogram(
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
        self.AQI_HIST = Histogram(
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

    def get_pressure(self):
        """Get pressure from the weather sensor."""
        pressure = bme280.get_pressure()
        self.PRESSURE.set(pressure)
        self.latest_values["pressure"] = pressure
        return pressure

    def get_humidity(self, humidity_compensation=None):
        """Get humidity from the weather sensor."""
        # Increase the humidity_compensation to increase the humidity.
        # Decrease it to decrease the humidity.
        humidity = bme280.get_humidity()

        if humidity_compensation:
            humidity = humidity + humidity_compensation
        self.HUMIDITY.set(humidity)
        self.latest_values["humidity"] = humidity
        return humidity

    @staticmethod
    def describe_humidity(humidity):
        """Convert relative humidity into good/bad description."""
        return "good" if 30 < humidity < 70 else "bad"

    def get_gas(self):
        """Get all gas readings."""
        try:
            readings = gas.read_all()
        except (OSError, ValueError) as exception:
            logging.warning(f"Failed to read gas sensor with error: {exception}")
        else:
            self.OXIDISING.set(readings.oxidising)
            self.OXIDISING_HIST.observe(readings.oxidising)
            self.REDUCING.set(readings.reducing)
            self.REDUCING_HIST.observe(readings.reducing)
            self.NH3.set(readings.nh3)
            self.NH3_HIST.observe(readings.nh3)
            self.latest_values["oxidising"] = readings.oxidising
            self.latest_values["reducing"] = readings.reducing
            self.latest_values["nh3"] = readings.nh3
            return readings

    def get_light(self):
        """Get all light readings."""
        try:
            lux = ltr559.get_lux()
            prox = ltr559.get_proximity()
        except OSError as exception:
            logging.warning(f"Failed to read light sensor with error: {exception}")
        else:
            self.LUX.set(lux)
            self.PROXIMITY.set(prox)
            self.latest_values["lux"] = lux
            self.latest_values["proximity"] = prox
            return lux, prox

    @staticmethod
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

    def read_pms_data(self) -> Optional[dict]:
        """Attempt to read data from PMS5003 and return it."""

    def get_particulates(self) -> Optional[dict[str, float]]:
        """Get the particulate matter readings."""
        try:
            pms_data = pms5003.read()
        except (pmsReadTimeoutError, pmsSerialTimeoutError, pmsChecksumMismatchError):
            logging.warning("Failed to read PMS5003")
            return None

        pm1 = pms_data.pm_ug_per_m3(1.0)
        pm25 = pms_data.pm_ug_per_m3(2.5)
        pm10 = pms_data.pm_ug_per_m3(10)
        myaqi = aqi.to_aqi([(aqi.POLLUTANT_PM25, self), (aqi.POLLUTANT_PM10, pm10)])

        self.PM1.set(pm1)
        self.PM25.set(pm25)
        self.PM10.set(pm10)
        self.PM1_HIST.observe(pm1)
        self.PM25_HIST.observe(pm25 - pm1)
        self.PM10_HIST.observe(pm10 - pm25)
        self.AQI.set(myaqi)
        self.AQI_HIST.observe(float(myaqi))

        self.latest_values["internal_aqi"] = myaqi

        return {"PM1": pm1, "PM25": pm25, "PM10": pm10, "myaqi": myaqi}

    def get_battery(self):
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
            return self._set_battery_values(battery_sensor)
        except (RuntimeError, OSError) as exception:
            logging.warning(f"Failed to read battery monitor with error: {exception}")
            return None, None

    # TODO Rename this here and in `get_battery`
    def _set_battery_values(self, battery_sensor):
        voltage_reading = battery_sensor.cell_voltage
        percentage_reading = battery_sensor.cell_percent
        self.latest_values["battery_voltage"] = voltage_reading
        self.latest_values["battery_percentage"] = percentage_reading
        logging.debug(f"Battery: {voltage_reading} Volts / {percentage_reading} %")
        self.BATTERY_VOLTAGE.set(voltage_reading or 0)
        self.BATTERY_PERCENTAGE.set(percentage_reading or 0)

        return voltage_reading, percentage_reading


class PressureAnalyzer:
    def __init__(self, max_values=1000):
        self.pressure_vals = []
        self.time_vals = []
        self.num_vals = max_values
        self.trend = "-"

    def _calculate_regression(self):
        line = numpy.polyfit(self.time_vals, self.pressure_vals, 1, full=True)
        slope = line[0][0]
        intercept = line[0][1]
        variance = numpy.var(self.pressure_vals)
        residuals = numpy.var(
            [
                slope * x + intercept - y
                for x, y in zip(self.time_vals, self.pressure_vals)
            ]
        )
        r_squared = 1 - residuals / variance
        change_per_hour = slope * 60 * 60
        return change_per_hour, r_squared

    def analyse_pressure(self, pressure, t):
        if len(self.pressure_vals) > self.num_vals:
            self.pressure_vals = self.pressure_vals[1:] + [pressure]
            self.time_vals = self.time_vals[1:] + [t]

            change_per_hour, r_squared = self._calculate_regression()
            mean_pressure = numpy.mean(self.pressure_vals)

            if r_squared > 0.5:
                if change_per_hour > 0.5:
                    self.trend = ">"
                elif change_per_hour < -0.5:
                    self.trend = "<"
                else:
                    self.trend = "-"
                if self.trend != "-" and abs(change_per_hour) > 3:
                    self.trend *= 2
        else:
            self.pressure_vals.append(pressure)
            self.time_vals.append(t)
            mean_pressure = numpy.mean(self.pressure_vals)
            change_per_hour = 0
            self.trend = "-"

        return mean_pressure, change_per_hour, self.trend

    @staticmethod
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
