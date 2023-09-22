#!/usr/bin/env python3
import argparse
import colorsys
import logging
import os
import time
from datetime import datetime, timedelta
from threading import Thread

import aqi
import board
import notecard.notecard as notecard
import numpy
import pytz
import requests
import SafecastPy
import ST7735
from adafruit_lc709203f import LC709203F, PackSize
from astral.geocoder import database, lookup
from astral.sun import sun
from bme280 import BME280
from dotenv import load_dotenv
from enviroplus import gas
from fonts.ttf import RobotoMedium as UserFont
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from periphery import Serial
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pms5003 import PMS5003
from pms5003 import ChecksumMismatchError as pmsChecksumMismatchError
from pms5003 import ReadTimeoutError as pmsReadTimeoutError
from pms5003 import SerialTimeoutError as pmsSerialTimeoutError
from prometheus_client import Gauge, Histogram, start_http_server

load_dotenv()

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus

try:
    # Transitional fix for breaking change in LTR559
    from ltr559 import LTR559

    ltr559 = LTR559()
except ImportError:
    import ltr559


logging.basicConfig(
    format="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)

logging.info(
    """enviroplus_exporter.py - Expose readings from the Enviro+ sensor by Pimoroni in Prometheus format

Press Ctrl+C to exit!

"""
)

DEBUG = os.getenv("DEBUG", "false") == "true"

bus = SMBus(1)
bme280 = BME280(i2c_dev=bus)
pms5003 = PMS5003()

battery_sensor = False
try:
    sensor = LC709203F(board.I2C())
    battery_sensor = True
except ValueError:
    pass

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

# Setup InfluxDB
# You can generate an InfluxDB Token from the Tokens Tab in the InfluxDB Cloud UI
INFLUXDB_URL = os.getenv(
    "INFLUXDB_URL", "https://us-central1-1.gcp.cloud2.influxdata.com"
)
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG_ID = os.getenv("INFLUXDB_ORG_ID", "")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "enviro")
INFLUXDB_SENSOR_LOCATION = os.getenv("INFLUXDB_SENSOR_LOCATION", "San Francisco")
INFLUXDB_TIME_BETWEEN_POSTS = int(os.getenv("INFLUXDB_TIME_BETWEEN_POSTS", "5"))
influxdb_client = InfluxDBClient(
    url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG_ID
)
influxdb_api = influxdb_client.write_api(write_options=SYNCHRONOUS)

# Setup Luftdaten
LUFTDATEN_TIME_BETWEEN_POSTS = int(os.getenv("LUFTDATEN_TIME_BETWEEN_POSTS", "30"))

# Setup Safecast
SAFECAST_TIME_BETWEEN_POSTS = int(os.getenv("SAFECAST_TIME_BETWEEN_POSTS", "300"))
SAFECAST_DEV_MODE = os.getenv("SAFECAST_DEV_MODE", "false") == "true"
SAFECAST_API_KEY = os.getenv("SAFECAST_API_KEY", "")
SAFECAST_API_KEY_DEV = os.getenv("SAFECAST_API_KEY_DEV", "")
SAFECAST_LATITUDE = os.getenv("SAFECAST_LATITUDE", "")
SAFECAST_LONGITUDE = os.getenv("SAFECAST_LONGITUDE", "")
SAFECAST_DEVICE_ID = int(os.getenv("SAFECAST_DEVICE_ID", "226"))
SAFECAST_LOCATION_NAME = os.getenv("SAFECAST_LOCATION_NAME", "")
if SAFECAST_DEV_MODE:
    # Post to the dev API
    safecast = SafecastPy.SafecastPy(
        api_key=SAFECAST_API_KEY_DEV,
        api_url=SafecastPy.DEVELOPMENT_API_URL,
    )
else:
    # Post to the production API
    safecast = SafecastPy.SafecastPy(
        api_key=SAFECAST_API_KEY,
    )

# Setup Blues Notecard
NOTECARD_TIME_BETWEEN_POSTS = int(os.getenv("NOTECARD_TIME_BETWEEN_POSTS", "600"))

# Setup LC709203F battery monitor
if battery_sensor:
    if DEBUG:
        logging.info("## LC709203F battery monitor ##")
    try:
        if DEBUG:
            logging.info(f"Sensor IC version: {hex(sensor.ic_version)}")
        # Set the battery pack size to 3000 mAh
        sensor.pack_size = PackSize.MAH3000
        sensor.init_RSOC()
        if DEBUG:
            logging.info(f"Battery size: {PackSize.string[sensor.pack_sizes]}")
    except RuntimeError as exception:
        logging.error(f"Failed to read sensor with error: {exception}")
        logging.info("Try setting the I2C clock speed to 10000Hz")


def get_cpu_temperature():
    """Get the temperature from the Raspberry Pi CPU."""
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = f.read()
        temp = int(temp) / 1000.0
        CPU_TEMPERATURE.set(temp)


def get_temperature(temperature_compensation):
    """Get temperature from the weather sensor."""
    # Increase the temperature_compensation to reduce the temperature.
    # Decrease it to increase the temperature.
    temperature = bme280.get_temperature()

    if temperature_compensation:
        temperature = temperature - temperature_compensation

    TEMPERATURE.set(temperature)  # Set to a given value


def get_pressure():
    """Get pressure from the weather sensor."""
    pressure = bme280.get_pressure()
    PRESSURE.set(pressure)


def get_humidity(humidity_compensation):
    """Get humidity from the weather sensor."""
    # Increase the humidity_compensation to increase the humidity.
    # Decrease it to decrease the humidity.
    humidity = bme280.get_humidity()

    if humidity_compensation:
        humidity = humidity + humidity_compensation

    HUMIDITY.set(humidity)


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


def get_particulates():
    """Get the particulate matter readings."""
    try:
        pms_data = pms5003.read()
    except (pmsReadTimeoutError, pmsSerialTimeoutError, pmsChecksumMismatchError):
        logging.warning("Failed to read PMS5003")
    else:
        PM1.set(pms_data.pm_ug_per_m3(1.0))
        PM25.set(pms_data.pm_ug_per_m3(2.5))
        PM10.set(pms_data.pm_ug_per_m3(10))

        PM1_HIST.observe(pms_data.pm_ug_per_m3(1.0))
        PM25_HIST.observe(pms_data.pm_ug_per_m3(2.5) - pms_data.pm_ug_per_m3(1.0))
        PM10_HIST.observe(pms_data.pm_ug_per_m3(10) - pms_data.pm_ug_per_m3(2.5))

        myaqi = aqi.to_aqi(
            [
                (aqi.POLLUTANT_PM25, pms_data.pm_ug_per_m3(2.5)),
                (aqi.POLLUTANT_PM10, pms_data.pm_ug_per_m3(10)),
            ]
        )

        AQI.set(myaqi)
        AQI_HIST.observe(float(myaqi))


def get_battery():
    """Get the battery voltage and percentage left."""
    try:
        voltage_reading = sensor.cell_voltage
        percentage_reading = sensor.cell_percent
        BATTERY_VOLTAGE.set(voltage_reading)
        BATTERY_PERCENTAGE.set(percentage_reading)
        if DEBUG:
            logging.info(
                f"Battery: {sensor.cell_voltage} Volts / {sensor.cell_percent} %"
            )
    except (RuntimeError, OSError) as exception:
        logging.warning(f"Failed to read battery monitor with error: {exception}")


def collect_all_data():
    """Collects all the data currently set."""
    sensor_data = {"temperature": TEMPERATURE.collect()[0].samples[0].value}
    sensor_data["humidity"] = HUMIDITY.collect()[0].samples[0].value
    sensor_data["pressure"] = PRESSURE.collect()[0].samples[0].value
    sensor_data["oxidising"] = OXIDISING.collect()[0].samples[0].value
    sensor_data["reducing"] = REDUCING.collect()[0].samples[0].value
    sensor_data["nh3"] = NH3.collect()[0].samples[0].value
    sensor_data["lux"] = LUX.collect()[0].samples[0].value
    sensor_data["proximity"] = PROXIMITY.collect()[0].samples[0].value
    sensor_data["pm1"] = PM1.collect()[0].samples[0].value
    sensor_data["pm25"] = PM25.collect()[0].samples[0].value
    sensor_data["pm10"] = PM10.collect()[0].samples[0].value
    sensor_data["cpu_temperature"] = CPU_TEMPERATURE.collect()[0].samples[0].value
    sensor_data["battery_voltage"] = BATTERY_VOLTAGE.collect()[0].samples[0].value
    sensor_data["battery_percentage"] = BATTERY_PERCENTAGE.collect()[0].samples[0].value
    sensor_data["aqi"] = AQI.collect()[0].samples[0].value
    return sensor_data


def post_to_influxdb():
    """Post all sensor data to InfluxDB."""
    while True:
        time.sleep(INFLUXDB_TIME_BETWEEN_POSTS)
        round(time.time())
        sensor_data = collect_all_data()
        data_points = [
            Point("enviroplus")
            .tag("location", INFLUXDB_SENSOR_LOCATION)
            .field(field_name, sensor_data[field_name])
            for field_name in sensor_data
        ]
        try:
            influxdb_api.write(bucket=INFLUXDB_BUCKET, record=data_points)
            if DEBUG:
                logging.info("InfluxDB response: OK")
        except Exception as exception:
            logging.warning(f"Exception sending to InfluxDB: {exception}")


def post_to_luftdaten():
    """Post relevant sensor data to luftdaten.info."""
    """Code from: https://github.com/sepulworld/balena-environ-plus"""
    LUFTDATEN_SENSOR_UID = f"raspi-{get_serial_number()}"
    while True:
        time.sleep(LUFTDATEN_TIME_BETWEEN_POSTS)
        sensor_data = collect_all_data()
        values = {
            "P2": sensor_data["pm25"],
            "P1": sensor_data["pm10"],
            "temperature": "{:.2f}".format(sensor_data["temperature"]),
            "pressure": "{:.2f}".format(sensor_data["pressure"] * 100),
            "humidity": "{:.2f}".format(sensor_data["humidity"]),
        }
        pm_values = dict(i for i in values.items() if i[0].startswith("P"))
        temperature_values = dict(i for i in values.items() if not i[0].startswith("P"))
        try:
            response_pin_1 = requests.post(
                "https://api.luftdaten.info/v1/push-sensor-data/",
                json={
                    "software_version": "enviro-plus 0.0.1",
                    "sensordatavalues": [
                        {"value_type": key, "value": val}
                        for key, val in pm_values.items()
                    ],
                },
                headers={
                    "X-PIN": "1",
                    "X-Sensor": LUFTDATEN_SENSOR_UID,
                    "Content-Type": "application/json",
                    "cache-control": "no-cache",
                },
            )

            response_pin_11 = requests.post(
                "https://api.luftdaten.info/v1/push-sensor-data/",
                json={
                    "software_version": "enviro-plus 0.0.1",
                    "sensordatavalues": [
                        {"value_type": key, "value": val}
                        for key, val in temperature_values.items()
                    ],
                },
                headers={
                    "X-PIN": "11",
                    "X-Sensor": LUFTDATEN_SENSOR_UID,
                    "Content-Type": "application/json",
                    "cache-control": "no-cache",
                },
            )

            if response_pin_1.ok and response_pin_11.ok:
                if DEBUG:
                    logging.info("Luftdaten response: OK")
            else:
                logging.warning("Luftdaten response: Failed")
        except Exception as exception:
            logging.warning(f"Exception sending to Luftdaten: {exception}")


def post_to_safecast():
    """Post all sensor data to Safecast.org."""
    while True:
        time.sleep(SAFECAST_TIME_BETWEEN_POSTS)
        sensor_data = collect_all_data()
        try:
            measurement = safecast.add_measurement(
                json={
                    "latitude": SAFECAST_LATITUDE,
                    "longitude": SAFECAST_LONGITUDE,
                    "value": sensor_data["pm1"],
                    "unit": "PM1 ug/m3",
                    "captured_at": datetime.datetime.now().astimezone().isoformat(),
                    "device_id": SAFECAST_DEVICE_ID,  # Enviro+
                    "location_name": SAFECAST_LOCATION_NAME,
                    "height": None,
                }
            )
            if DEBUG:
                logging.info(
                    f'Safecast PM1 measurement created, id: {measurement["id"]}'
                )

            measurement = safecast.add_measurement(
                json={
                    "latitude": SAFECAST_LATITUDE,
                    "longitude": SAFECAST_LONGITUDE,
                    "value": sensor_data["pm25"],
                    "unit": "PM2.5 ug/m3",
                    "captured_at": datetime.datetime.now().astimezone().isoformat(),
                    "device_id": SAFECAST_DEVICE_ID,  # Enviro+
                    "location_name": SAFECAST_LOCATION_NAME,
                    "height": None,
                }
            )
            if DEBUG:
                logging.info(
                    f'Safecast PM2.5 measurement created, id: {measurement["id"]}'
                )

            measurement = safecast.add_measurement(
                json={
                    "latitude": SAFECAST_LATITUDE,
                    "longitude": SAFECAST_LONGITUDE,
                    "value": sensor_data["pm10"],
                    "unit": "PM10 ug/m3",
                    "captured_at": datetime.datetime.now().astimezone().isoformat(),
                    "device_id": SAFECAST_DEVICE_ID,  # Enviro+
                    "location_name": SAFECAST_LOCATION_NAME,
                    "height": None,
                }
            )
            if DEBUG:
                logging.info(
                    f'Safecast PM10 measurement created, id: {measurement["id"]}'
                )

            measurement = safecast.add_measurement(
                json={
                    "latitude": SAFECAST_LATITUDE,
                    "longitude": SAFECAST_LONGITUDE,
                    "value": sensor_data["temperature"],
                    "unit": "Temperature C",
                    "captured_at": datetime.datetime.now().astimezone().isoformat(),
                    "device_id": SAFECAST_DEVICE_ID,  # Enviro+
                    "location_name": SAFECAST_LOCATION_NAME,
                    "height": None,
                }
            )
            if DEBUG:
                logging.info(
                    f'Safecast Temperature measurement created, id: {measurement["id"]}'
                )

            measurement = safecast.add_measurement(
                json={
                    "latitude": SAFECAST_LATITUDE,
                    "longitude": SAFECAST_LONGITUDE,
                    "value": sensor_data["humidity"],
                    "unit": "Humidity %",
                    "captured_at": datetime.datetime.now().astimezone().isoformat(),
                    "device_id": SAFECAST_DEVICE_ID,  # Enviro+
                    "location_name": SAFECAST_LOCATION_NAME,
                    "height": None,
                }
            )
            if DEBUG:
                logging.info(
                    f'Safecast Humidity measurement created, id: {measurement["id"]}'
                )

            measurement = safecast.add_measurement(
                json={
                    "latitude": SAFECAST_LATITUDE,
                    "longitude": SAFECAST_LONGITUDE,
                    "value": sensor_data["cpu_temperature"],
                    "unit": "CPU temperature C",
                    "captured_at": datetime.datetime.now().astimezone().isoformat(),
                    "device_id": SAFECAST_DEVICE_ID,  # Enviro+
                    "location_name": SAFECAST_LOCATION_NAME,
                    "height": None,
                }
            )
            if DEBUG:
                logging.info(
                    f'Safecast CPU temperature measurement created, id: {measurement["id"]}'
                )
        except Exception as exception:
            logging.warning(f"Exception sending to Safecast: {exception}")


def post_to_notehub():
    """Post all sensor data to Notehub.io."""
    while True:
        time.sleep(NOTECARD_TIME_BETWEEN_POSTS)
        try:
            notecard_port = Serial("/dev/ttyACM0", 9600)
            card = notecard.OpenSerial(notecard_port)
            # Setup data
            sensor_data = collect_all_data()
            for sensor_data_key in sensor_data:
                data_unit = None
                if "temperature" in sensor_data_key:
                    data_unit = "°C"
                elif "humidity" in sensor_data_key:
                    data_unit = "%RH"
                elif "pressure" in sensor_data_key:
                    data_unit = "hPa"
                elif (
                    "oxidising" in sensor_data_key
                    or "reducing" in sensor_data_key
                    or "nh3" in sensor_data_key
                ):
                    data_unit = "kOhms"
                elif "proximity" in sensor_data_key:
                    pass
                elif "lux" in sensor_data_key:
                    data_unit = "Lux"
                elif "pm" in sensor_data_key:
                    data_unit = "ug/m3"
                elif "battery_voltage" in sensor_data_key:
                    data_unit = "V"
                elif "battery_percentage" in sensor_data_key:
                    data_unit = "%"
                request = {
                    "req": "note.add",
                    "body": {
                        sensor_data_key: sensor_data[sensor_data_key],
                        "units": data_unit,
                    },
                }
                try:
                    response = card.Transaction(request)
                    if DEBUG:
                        logging.info(f"Notecard response: {response}")
                except Exception as exception:
                    logging.warning(f"Notecard data setup error: {exception}")
            # Sync data with Notehub
            request = {"req": "service.sync"}
            try:
                response = card.Transaction(request)
                if DEBUG:
                    logging.info(f"Notecard response: {response}")
            except Exception as exception:
                logging.warning(f"Notecard sync error: {exception}")
        except Exception as exception:
            # TODO: Do we need to reboot here? Or is this missing tty temporary?
            logging.warning(f"Error opening notecard: {exception}")


def get_serial_number():
    """Get Raspberry Pi serial number to use as LUFTDATEN_SENSOR_UID."""
    with open("/proc/cpuinfo", "r") as f:
        for line in f:
            if line[:6] == "Serial":
                return str(line.split(":")[1].strip())


def str_to_bool(value):
    if value.lower() in {"false", "f", "0", "no", "n"}:
        return False
    elif value.lower() in {"true", "t", "1", "yes", "y"}:
        return True
    raise ValueError(f"{value} is not a valid boolean value")


def calculate_y_pos(x, centre):
    """Calculates the y-coordinate on a parabolic curve, given x."""
    centre = 80
    y = 1 / centre * (x - centre) ** 2

    return int(y)


def circle_coordinates(x, y, radius):
    """Calculates the bounds of a circle, given centre and radius."""

    x1 = x - radius  # Left
    x2 = x + radius  # Right
    y1 = y - radius  # Bottom
    y2 = y + radius  # Top

    return (x1, y1, x2, y2)


def map_colour(x, centre, start_hue, end_hue, day):
    """Given an x coordinate and a centre point, a start and end hue (in degrees),
    and a Boolean for day or night (day is True, night False), calculate a colour
    hue representing the 'colour' of that time of day."""

    start_hue = start_hue / 360  # Rescale to between 0 and 1
    end_hue = end_hue / 360

    sat = 1.0

    # Dim the brightness as you move from the centre to the edges
    val = 1 - (abs(centre - x) / (2 * centre))

    # Ramp up towards centre, then back down
    if x > centre:
        x = (2 * centre) - x

    # Calculate the hue
    hue = start_hue + ((x / centre) * (end_hue - start_hue))

    # At night, move towards purple/blue hues and reverse dimming
    if not day:
        hue = 1 - hue
        val = 1 - val

    r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, val)]

    return (r, g, b)


def x_from_sun_moon_time(progress, period, x_range):
    """Recalculate/rescale an amount of progress through a time period."""

    x = int((progress / period) * x_range)

    return x


def sun_moon_time(city_name, time_zone):
    """Calculate the progress through the current sun/moon period (i.e day or
    night) from the last sunrise or sunset, given a datetime object 't'."""

    city = lookup(city_name, database())

    # Datetime objects for yesterday, today, tomorrow
    utc = pytz.utc
    utc_dt = datetime.now(tz=utc)
    local_dt = utc_dt.astimezone(pytz.timezone(time_zone))
    today = local_dt.date()
    yesterday = today - timedelta(1)
    tomorrow = today + timedelta(1)

    # Sun objects for yesterday, today, tomorrow
    sun_yesterday = sun(city.observer, date=yesterday)
    sun_today = sun(city.observer, date=today)
    sun_tomorrow = sun(city.observer, date=tomorrow)

    # Work out sunset yesterday, sunrise/sunset today, and sunrise tomorrow
    sunset_yesterday = sun_yesterday["sunset"]
    sunrise_today = sun_today["sunrise"]
    sunset_today = sun_today["sunset"]
    sunrise_tomorrow = sun_tomorrow["sunrise"]

    # Work out lengths of day or night period and progress through period
    if sunrise_today < local_dt < sunset_today:
        day = True
        period = sunset_today - sunrise_today
        # mid = sunrise_today + (period / 2)
        progress = local_dt - sunrise_today

    elif local_dt > sunset_today:
        day = False
        period = sunrise_tomorrow - sunset_today
        # mid = sunset_today + (period / 2)
        progress = local_dt - sunset_today

    else:
        day = False
        period = sunrise_today - sunset_yesterday
        # mid = sunset_yesterday + (period / 2)
        progress = local_dt - sunset_yesterday

    # Convert time deltas to seconds
    progress = progress.total_seconds()
    period = period.total_seconds()

    return (progress, period, day, local_dt)


def draw_background(progress, period, day):
    """Given an amount of progress through the day or night, draw the
    background colour and overlay a blurred sun/moon."""

    # x-coordinate for sun/moon
    x = x_from_sun_moon_time(progress, period, WIDTH)

    # If it's day, then move right to left
    if day:
        x = WIDTH - x

    # Calculate position on sun/moon's curve
    centre = WIDTH / 2
    y = calculate_y_pos(x, centre)

    # Background colour
    background = map_colour(x, 80, mid_hue, day_hue, day)

    # New image for background colour
    img = Image.new("RGBA", (WIDTH, HEIGHT), color=background)
    Image.new("RGBA", (WIDTH, HEIGHT), color=(0, 0, 0))
    # draw = ImageDraw.Draw(img)

    # New image for sun/moon overlay
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), color=(0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # Draw the sun/moon
    circle = circle_coordinates(x, y, sun_radius)
    overlay_draw.ellipse(circle, fill=(200, 200, 50, opacity))

    # Overlay the sun/moon on the background as an alpha matte
    composite = Image.alpha_composite(img, overlay).filter(
        ImageFilter.GaussianBlur(radius=blur)
    )

    return composite


def overlay_text(img, position, text, font, align_right=False, rectangle=False):
    draw = ImageDraw.Draw(img)
    w, h = font.getsize(text)
    if align_right:
        x, y = position
        x -= w
        position = (x, y)
    if rectangle:
        x += 1
        y += 1
        position = (x, y)
        border = 1
        rect = (x - border, y, x + w, y + h + border)
        rect_img = Image.new("RGBA", (WIDTH, HEIGHT), color=(0, 0, 0, 0))
        rect_draw = ImageDraw.Draw(rect_img)
        rect_draw.rectangle(rect, (255, 255, 255))
        rect_draw.text(position, text, font=font, fill=(0, 0, 0, 0))
        img = Image.alpha_composite(img, rect_img)
    else:
        draw.text(position, text, font=font, fill=(255, 255, 255))
    return img


def get_cpu_temperature():
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = f.read()
        temp = int(temp) / 1000.0
    return temp


def correct_humidity(humidity, temperature, corr_temperature):
    dewpoint = temperature - ((100 - humidity) / 5)
    corr_humidity = 100 - (5 * (corr_temperature - dewpoint))
    return min(100, corr_humidity)


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


def describe_aqi(aqi: int) -> str:
    # Calculate the Air Quality using the EPA's forumla
    # https://www.epa.vic.gov.au/for-community/monitoring-your-environment/about-epa-airwatch/calculate-air-quality-categories
    # HomeKit	1		2		3		4		5
    # PM2.5	<27		27–62		62–97		97–370		>370
    # PM10	<40		40–80		80–120		120–240		>240
    # Good	Fair	Poor	Very poor	Extremely poor
    if aqi < 0:
        return "???"
    if 0 < aqi < 50:
        return "Good"
    if 51 <= aqi <= 100:
        return "OK"
    if 101 <= aqi <= 150:
        return "Poor"
    if 151 <= aqi <= 200:
        return "Bad"
    if 201 <= aqi <= 300:
        return "Very Bad"
    return "XXX" if aqi > 300 else "?"


def get_external_AQI() -> int:
    # Set the API endpoint and parameters
    LATITUDE = os.getenv("LATITUDE", "")
    LONGITUDE = os.getenv("LONGITUDE", "")
    WAQI_API_KEY = os.getenv("WAQI_API_KEY", "")
    url = f"https://api.waqi.info/feed/geo:{LATITUDE};{LONGITUDE}/?token={WAQI_API_KEY}"

    # Send the request and get the response
    response = requests.get(url, timeout=10)

    # Check if the request was successful
    if response.status_code == 200:
        data = response.json()
        if data["status"] == "ok":
            return int(data["data"]["aqi"])
        else:
            print("Error:", data["data"])
    print("Failed to retrieve AQI. Status code:", response.status_code, response.text)
    return -1


# Initialise the LCD
disp = ST7735.ST7735(
    port=0, cs=1, dc=9, backlight=12, rotation=270, spi_speed_hz=10000000
)

disp.begin()

WIDTH = disp.width
HEIGHT = disp.height

# The city and timezone that you want to display.
city_name = "San Francisco"
time_zone = "America/Los_Angeles"

# Values that alter the look of the background
blur = 50
opacity = 125

mid_hue = 0
day_hue = 25

sun_radius = 50

# Fonts
font_sm = ImageFont.truetype(UserFont, 12)
font_lg = ImageFont.truetype(UserFont, 14)

# Margins
margin = 3


min_temp = None
max_temp = None

factor = 2.25
cpu_temps = [get_cpu_temperature()] * 5

# Pressure variables
pressure_vals = []
time_vals = []
num_vals = 1000
interval = 1
trend = "-"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-b",
        "--bind",
        metavar="ADDRESS",
        default="0.0.0.0",
        help="Specify alternate bind address [default: 0.0.0.0]",
    )
    parser.add_argument(
        "-p",
        "--port",
        metavar="PORT",
        default=8000,
        type=int,
        help="Specify alternate port [default: 8000]",
    )
    parser.add_argument(
        "-e",
        "--enviro",
        metavar="ENVIRO",
        type=str_to_bool,
        default="false",
        help="Device is an Enviro (not Enviro+) so don't fetch data from particulate sensor as it doesn't exist [default: false]",
    )
    parser.add_argument(
        "-t",
        "--temp",
        metavar="TEMPERATURE",
        type=float,
        help="The temperature compensation value to get better temperature results when the Enviro+ pHAT is too close to the Raspberry Pi board",
    )
    parser.add_argument(
        "-u",
        "--humid",
        metavar="HUMIDITY",
        type=float,
        help="The humidity compensation value to get better humidity results when the Enviro+ pHAT is too close to the Raspberry Pi board",
    )
    parser.add_argument(
        "-d",
        "--debug",
        metavar="DEBUG",
        type=str_to_bool,
        help="Turns on more vebose logging, showing sensor output and post responses [default: false]",
    )
    parser.add_argument(
        "-i",
        "--influxdb",
        metavar="INFLUXDB",
        type=str_to_bool,
        default="false",
        help="Post sensor data to InfluxDB Cloud [default: false]",
    )
    parser.add_argument(
        "-l",
        "--luftdaten",
        metavar="LUFTDATEN",
        type=str_to_bool,
        default="false",
        help="Post sensor data to Luftdaten.info [default: false]",
    )
    parser.add_argument(
        "-s",
        "--safecast",
        metavar="SAFECAST",
        type=str_to_bool,
        default="false",
        help="Post sensor data to Safecast.org [default: false]",
    )
    parser.add_argument(
        "-n",
        "--notecard",
        metavar="NOTECARD",
        type=str_to_bool,
        default="false",
        help="Post sensor data to Notehub.io via Notecard LTE [default: false]",
    )
    args = parser.parse_args()

    # Start up the server to expose the metrics.
    start_http_server(addr=args.bind, port=args.port)
    # Generate some requests.

    if args.debug:
        DEBUG = True

    if args.temp:
        logging.info(
            f"Using temperature compensation, reducing the output value by {args.temp}° to account for heat leakage from Raspberry Pi board"
        )

    if args.humid:
        logging.info(
            f"Using humidity compensation, increasing the output value by {args.humid}% to account for heat leakage from Raspberry Pi board"
        )

    if args.influxdb:
        # Post to InfluxDB in another thread
        logging.info(
            "Sensor data will be posted to InfluxDB every {} seconds".format(
                INFLUXDB_TIME_BETWEEN_POSTS
            )
        )
        influx_thread = Thread(target=post_to_influxdb)
        influx_thread.start()

    if args.luftdaten:
        # Post to Luftdaten in another thread
        LUFTDATEN_SENSOR_UID = "raspi-" + get_serial_number()
        logging.info(
            "Sensor data will be posted to Luftdaten every {} seconds for the UID {}".format(
                LUFTDATEN_TIME_BETWEEN_POSTS, LUFTDATEN_SENSOR_UID
            )
        )
        luftdaten_thread = Thread(target=post_to_luftdaten)
        luftdaten_thread.start()

    if args.safecast:
        # Post to Safecast in another thread
        safecast_api_url = SafecastPy.PRODUCTION_API_URL
        if SAFECAST_DEV_MODE:
            safecast_api_url = SafecastPy.DEVELOPMENT_API_URL
        logging.info(
            "Sensor data will be posted to {} every {} seconds".format(
                safecast_api_url, SAFECAST_TIME_BETWEEN_POSTS
            )
        )
        influx_thread = Thread(target=post_to_safecast)
        influx_thread.start()

    if args.notecard:
        # Post to Notehub via Notecard in another thread
        logging.info(
            "Sensor data will be posted to Notehub via Notecard every {} seconds".format(
                NOTECARD_TIME_BETWEEN_POSTS
            )
        )
        notecard_thread = Thread(target=post_to_notehub)
        notecard_thread.start()

    logging.info("Listening on http://{}:{}".format(args.bind, args.port))

    start_time = time.time()

    while True:
        get_temperature(args.temp)
        get_humidity(args.humid)
        get_pressure()
        get_light()
        get_gas()
        if not args.enviro:
            get_particulates()
        get_cpu_temperature()
        if battery_sensor:
            get_battery()
        if DEBUG:
            logging.info("Sensor data: {}".format(collect_all_data()))

        path = os.path.dirname(os.path.realpath(__file__))
        progress, period, day, local_dt = sun_moon_time(city_name, time_zone)
        background = draw_background(progress, period, day)

        # Time.
        time_elapsed = time.time() - start_time
        date_string = local_dt.strftime("%d %b %y").lstrip("0")
        time_string = local_dt.strftime("%I:%M:%S")
        img = overlay_text(background, (0 + margin, 0 + margin), time_string, font_lg)
        img = overlay_text(
            img, (WIDTH - margin, 0 + margin), date_string, font_lg, align_right=True
        )

        # Temperature

        # Corrected temperature
        cpu_temp = get_cpu_temperature()
        cpu_temps = cpu_temps[1:] + [cpu_temp]
        avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
        corr_temperature = TEMPERATURE.collect()[0].samples[0].value - (
            (avg_cpu_temp - TEMPERATURE.collect()[0].samples[0].value) / factor
        )

        if time_elapsed > 30:
            if min_temp is None or max_temp is None:
                min_temp = corr_temperature
                max_temp = corr_temperature

            elif corr_temperature < min_temp:
                min_temp = corr_temperature
            elif corr_temperature > max_temp:
                max_temp = corr_temperature
        temp_string = f"{(corr_temperature*1.8)+32:.0f}°F"
        img = overlay_text(img, (68, 18), temp_string, font_lg, align_right=True)
        spacing = font_lg.getsize(temp_string)[1] + 1
        if min_temp is not None and max_temp is not None:
            range_string = f"{(min_temp*1.8)+32:.0f}-{(max_temp*1.8)+32:.0f}"
        else:
            range_string = "------"
        img = overlay_text(
            img,
            (68, 18 + spacing),
            range_string,
            font_sm,
            align_right=True,
            rectangle=True,
        )
        temp_icon = Image.open(f"{path}/icons/temperature.png")
        img.paste(temp_icon, (margin, 18), mask=temp_icon)

        # Humidity
        corr_humidity = correct_humidity(
            HUMIDITY.collect()[0].samples[0].value,
            TEMPERATURE.collect()[0].samples[0].value,
            corr_temperature,
        )
        humidity_string = f"{corr_humidity:.0f}%"
        img = overlay_text(img, (68, 48), humidity_string, font_lg, align_right=True)
        spacing = font_lg.getsize(humidity_string)[1] + 1
        humidity_desc = describe_humidity(corr_humidity).upper()
        img = overlay_text(
            img,
            (68, 48 + spacing),
            humidity_desc,
            font_sm,
            align_right=True,
            rectangle=True,
        )
        humidity_icon = Image.open(f"{path}/icons/humidity-{humidity_desc.lower()}.png")
        img.paste(humidity_icon, (margin, 48), mask=humidity_icon)

        internal_aqi: int = int(
            aqi.to_aqi(
                [
                    (aqi.POLLUTANT_PM25, PM25.collect()[0].samples[0].value),
                    (aqi.POLLUTANT_PM10, PM10.collect()[0].samples[0].value),
                ]
            )
        )
        external_aqi = get_external_AQI()

        internal_aqi_str = f"AQI: {internal_aqi}/{external_aqi}"
        img = overlay_text(
            img, (WIDTH - margin, 18), internal_aqi_str, font_lg, align_right=True
        )
        spacing = font_lg.getsize(internal_aqi_str.replace(",", ""))[1] + 1

        aqi_desc = describe_aqi(internal_aqi).upper()
        img = overlay_text(
            img,
            (WIDTH - margin - 1, 18 + spacing),
            aqi_desc,
            font_sm,
            align_right=True,
            rectangle=True,
        )
        if external_aqi > 101:
            external_aqi_icon = Image.open(f"{path}/icons/aqi-bad.png")
        else:
            external_aqi_icon = Image.open(f"{path}/icons/aqi.png")
        img.paste(external_aqi_icon, (80, 18), mask=external_aqi_icon.split()[-1])

        # External AQI
        # external_aqi_str = f"ExtAQI: {int(external_aqi):,}"
        # img = overlay_text(
        #     img, (WIDTH - margin, 48), external_aqi_str, font_lg, align_right=True
        # )
        # spacing = font_lg.getsize(external_aqi_str.replace(",", ""))[1] + 1

        # external_aqi_desc = describe_aqi(external_aqi).upper()
        # img = overlay_text(
        #     img,
        #     (WIDTH - margin - 1, 48 + spacing),
        #     external_aqi_desc,
        #     font_sm,
        #     align_right=True,
        #     rectangle=True,
        # )
        # if external_aqi > 101:
        #     external_aqi_icon = Image.open(f"{path}/icons/aqi-bad.png")
        # else:
        #     external_aqi_icon = Image.open(f"{path}/icons/aqi.png")
        # img.paste(external_aqi_icon, (80, 48), mask=external_aqi_icon)

        # Pressure

        t = time.time()
        mean_pressure, change_per_hour, trend = analyse_pressure(
            PRESSURE.collect()[0].samples[0].value, t
        )
        pressure_string = f"{int(mean_pressure):,} {trend}"
        img = overlay_text(
            img, (WIDTH - margin, 48), pressure_string, font_lg, align_right=True
        )
        pressure_desc = describe_pressure(mean_pressure).upper()
        spacing = font_lg.getsize(pressure_string.replace(",", ""))[1] + 1
        img = overlay_text(
            img,
            (WIDTH - margin - 1, 48 + spacing),
            pressure_desc,
            font_sm,
            align_right=True,
            rectangle=True,
        )
        pressure_icon = Image.open(f"{path}/icons/weather-{pressure_desc.lower()}.png")
        img.paste(pressure_icon, (80, 48), mask=pressure_icon)

        # Display image
        # Light
        # print(f"Lux: {LUX.collect()[0].samples[0].value}")
        if LUX.collect()[0].samples[0].value < 10:
            disp.set_backlight(0)
            image_blank = Image.new("RGBA", (WIDTH, HEIGHT), color=(0, 0, 0))
            disp.display(image_blank)
        else:
            disp.set_backlight(1)
            disp.display(img)
        time.sleep(5)
