import datetime
import logging
import os
import time
from threading import Thread

import notecard.notecard as notecard
import requests
import SafecastPy
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from periphery import Serial

from sensors import collect_all_data

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


def get_serial_number():
    """Get Raspberry Pi serial number to use as LUFTDATEN_SENSOR_UID."""
    with open("/proc/cpuinfo", "r") as f:
        for line in f:
            if line[:6] == "Serial":
                return str(line.split(":")[1].strip())


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
                timeout=10,
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
                timeout=10,
            )

            if response_pin_1.ok and response_pin_11.ok:
                logging.debug("Luftdaten response: OK")
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
            logging.debug(f'Safecast PM1 measurement created, id: {measurement["id"]}')

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
            logging.debug(
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
            logging.debug(f'Safecast PM10 measurement created, id: {measurement["id"]}')

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
            logging.debug(
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
            logging.debug(
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
            logging.debug(
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
                    logging.debug(f"Notecard response: {response}")
                except Exception as exception:
                    logging.warning(f"Notecard data setup error: {exception}")
            # Sync data with Notehub
            request = {"req": "service.sync"}
            try:
                response = card.Transaction(request)
                logging.debug(f"Notecard response: {response}")
            except Exception as exception:
                logging.warning(f"Notecard sync error: {exception}")
        except Exception as exception:
            # TODO: Do we need to reboot here? Or is this missing tty temporary?
            logging.warning(f"Error opening notecard: {exception}")


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
            logging.debug("InfluxDB response: OK")
        except Exception as exception:
            logging.warning(f"Exception sending to InfluxDB: {exception}")
