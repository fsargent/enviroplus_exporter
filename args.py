import argparse


def str_to_bool(value):
    if value.lower() in {"false", "f", "0", "no", "n"}:
        return False
    elif value.lower() in {"true", "t", "1", "yes", "y"}:
        return True
    raise ValueError(f"{value} is not a valid boolean value")


def setup_arguments():
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

    # if args.influxdb:
    #     # Post to InfluxDB in another thread
    #     logging.info(
    #         "Sensor data will be posted to InfluxDB every {} seconds".format(
    #             INFLUXDB_TIME_BETWEEN_POSTS
    #         )
    #     )
    #     influx_thread = Thread(target=post_to_influxdb)
    #     influx_thread.start()

    # if args.luftdaten:
    #     # Post to Luftdaten in another thread
    #     LUFTDATEN_SENSOR_UID = "raspi-" + get_serial_number()
    #     logging.info(
    #         "Sensor data will be posted to Luftdaten every {} seconds for the UID {}".format(
    #             LUFTDATEN_TIME_BETWEEN_POSTS, LUFTDATEN_SENSOR_UID
    #         )
    #     )
    #     luftdaten_thread = Thread(target=post_to_luftdaten)
    #     luftdaten_thread.start()

    # if args.safecast:
    #     # Post to Safecast in another thread
    #     safecast_api_url = SafecastPy.PRODUCTION_API_URL
    #     if SAFECAST_DEV_MODE:
    #         safecast_api_url = SafecastPy.DEVELOPMENT_API_URL
    #     logging.info(
    #         "Sensor data will be posted to {} every {} seconds".format(
    #             safecast_api_url, SAFECAST_TIME_BETWEEN_POSTS
    #         )
    #     )
    #     influx_thread = Thread(target=post_to_safecast)
    #     influx_thread.start()

    # if args.notecard:
    #     # Post to Notehub via Notecard in another thread
    #     logging.info(
    #         "Sensor data will be posted to Notehub via Notecard every {} seconds".format(
    #             NOTECARD_TIME_BETWEEN_POSTS
    #         )
    #     )
    #     notecard_thread = Thread(target=post_to_notehub)
    #     notecard_thread.start()
    return args
