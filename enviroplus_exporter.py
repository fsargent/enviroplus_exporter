#!/usr/bin/env python3
import logging
import os
import time

from dotenv import load_dotenv
from PIL import Image
from prometheus_client import start_http_server

from aqi_utilities import describe_aqi
from args import setup_arguments
from display import Display

# from clients import post_to_luftdaten, post_to_safecast, post_to_notehub
from sensors import (
    Celsius,
    analyse_pressure,
    collect_all_data,
    describe_humidity,
    describe_pressure,
)

load_dotenv()

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


# Initialze Display
disp = Display()

if __name__ == "__main__":
    args = setup_arguments()

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
    # The city and timezone that you want to display.
    city_name = "San Francisco"
    time_zone = "America/Los_Angeles"

    logging.info(f"Listening on http://{args.bind}:{args.port}")

    start_time = time.time()

    display = Display()
    LUX_THRESHOLD = 0
    while True:
        if DEBUG:
            logging.info(f"Sensor data: {collect_all_data()}")

        sensor_data = collect_all_data()

        path = os.path.dirname(os.path.realpath(__file__))

        progress, period, day, local_dt = display.sun_moon_time(city_name, time_zone)
        background = display.draw_background(
            progress, period, day, sensor_data["external_aqi"]
        )

        # Time.
        # time_elapsed = time.time() - start_time
        date_string = local_dt.strftime("%d %b %y").lstrip("0")
        time_string = local_dt.strftime("%I:%M:%S")
        img = display.overlay_text(
            background, (0 + disp.margin, 0 + disp.margin), time_string, disp.font_lg
        )
        img = display.overlay_text(
            img,
            (disp.WIDTH - disp.margin, 0 + disp.margin),
            date_string,
            disp.font_lg,
            align_right=True,
        )

        # Temperature
        temperature = Celsius(sensor_data["temperature"])
        img = display.overlay_text(
            img, (68, 18), temperature.to_fahrenheit(), disp.font_lg, align_right=True
        )
        spacing = disp.font_lg.getsize(temperature.to_fahrenheit())[1] + 1

        # img = display.overlay_text(
        #     img,
        #     (68, 18 + spacing),
        #     range_string,
        #     disp.font_sm,
        #     align_right=True,
        #     rectangle=True,
        # )
        temp_icon = Image.open(f"{path}/icons/temperature.png")
        img.paste(temp_icon, (disp.margin, 18), mask=temp_icon)

        # Humidity
        corr_humidity = sensor_data["humidity"]
        humidity_string = f"{corr_humidity:.0f}%"
        img = display.overlay_text(
            img, (68, 48), humidity_string, disp.font_lg, align_right=True
        )
        spacing = disp.font_lg.getsize(humidity_string)[1] + 1
        humidity_desc = describe_humidity(corr_humidity).upper()
        img = display.overlay_text(
            img,
            (68, 48 + spacing),
            humidity_desc,
            disp.font_sm,
            align_right=True,
            rectangle=True,
        )
        humidity_icon = Image.open(f"{path}/icons/humidity-{humidity_desc.lower()}.png")
        img.paste(humidity_icon, (disp.margin, 48), mask=humidity_icon)

        internal_aqi_str = (
            f"{sensor_data['internal_aqi']}/{sensor_data['external_aqi']}"
        )
        img = display.overlay_text(
            img,
            (disp.WIDTH - disp.margin, 18),
            internal_aqi_str,
            disp.font_lg,
            align_right=True,
        )
        spacing = disp.font_lg.getsize(internal_aqi_str.replace(",", ""))[1] + 1

        aqi_desc = describe_aqi(sensor_data["external_aqi"]).upper()
        img = display.overlay_text(
            img,
            (disp.WIDTH - disp.margin - 1, 18 + spacing),
            aqi_desc,
            disp.font_sm,
            align_right=True,
            rectangle=True,
        )
        if sensor_data["external_aqi"] > 101:
            external_aqi_icon = Image.open(f"{path}/icons/aqi-bad.png")
        else:
            external_aqi_icon = Image.open(f"{path}/icons/aqi.png")
        img.paste(external_aqi_icon, (80, 18), mask=external_aqi_icon.split()[-1])

        # Pressure
        t = time.time()
        mean_pressure, change_per_hour, trend = analyse_pressure(
            sensor_data["pressure"], t
        )
        pressure_string = f"{int(mean_pressure):,} {trend}"
        img = display.overlay_text(
            img,
            (disp.WIDTH - disp.margin, 48),
            pressure_string,
            disp.font_lg,
            align_right=True,
        )
        pressure_desc = describe_pressure(mean_pressure).upper()
        spacing = disp.font_lg.getsize(pressure_string.replace(",", ""))[1] + 1
        img = display.overlay_text(
            img,
            (disp.WIDTH - disp.margin - 1, 48 + spacing),
            pressure_desc,
            disp.font_sm,
            align_right=True,
            rectangle=True,
        )
        pressure_icon = Image.open(f"{path}/icons/weather-{pressure_desc.lower()}.png")
        img.paste(pressure_icon, (80, 48), mask=pressure_icon)

        # Light
        if sensor_data["lux"] < LUX_THRESHOLD:
            disp.set_backlight(0)
            image_blank = Image.new("RGBA", (disp.WIDTH, disp.HEIGHT), color=(0, 0, 0))
            disp.display(image_blank)
        else:
            disp.set_backlight(1)
            disp.display(img)
        time.sleep(5)
