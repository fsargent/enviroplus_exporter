import colorsys
from datetime import datetime, timedelta

import pytz
import ST7735  # LCD
from astral.geocoder import database, lookup
from astral.sun import sun
from fonts.ttf import RobotoMedium as UserFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from aqi_utilities import aqi_to_color


class Display:
    def __init__(self):
        self.disp = ST7735.ST7735(
            port=0, cs=1, dc=9, backlight=12, rotation=270, spi_speed_hz=10000000
        )

        self.disp.begin()
        self.WIDTH = self.disp.width
        self.HEIGHT = self.disp.height

        # Values that alter the look of the background
        self.blur = 50
        self.opacity = 125

        self.mid_hue = 0
        self.day_hue = 25

        self.sun_radius = 50

        # Fonts
        self.font_sm = ImageFont.truetype(UserFont, 12)
        self.font_lg = ImageFont.truetype(UserFont, 14)

        # Margins
        self.margin = 3

    @staticmethod
    def calculate_y_pos(x, centre):
        """Calculate the y-coordinate on a parabolic curve, given x."""
        centre = 80
        y = 1 / centre * (x - centre) ** 2

        return int(y)

    @staticmethod
    def circle_coordinates(x, y, radius):
        """Calculate the bounds of a circle, given centre and radius."""

        x1 = x - radius  # Left
        x2 = x + radius  # Right
        y1 = y - radius  # Bottom
        y2 = y + radius  # Top

        return (x1, y1, x2, y2)

    @staticmethod
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

    @staticmethod
    def x_from_sun_moon_time(progress, period, x_range):
        """Recalculate/rescale an amount of progress through a time period."""

        x = int((progress / period) * x_range)

        return x

    @staticmethod
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

    def draw_background(self, progress, period, day, aqi):
        """Given an amount of progress through the day or night, draw the
        background colour and overlay a blurred sun/moon."""

        # x-coordinate for sun/moon
        x = self.x_from_sun_moon_time(progress, period, self.WIDTH)

        # If it's day, then move right to left
        if day:
            x = self.WIDTH - x

        # Calculate position on sun/moon's curve
        centre = self.WIDTH / 2
        y = self.calculate_y_pos(x, centre)

        # Background colour
        background = aqi_to_color(aqi)

        # New image for background colour
        img = Image.new("RGBA", (self.WIDTH, self.HEIGHT), color=background)
        Image.new("RGBA", (self.WIDTH, self.HEIGHT), color=(0, 0, 0))
        # draw = ImageDraw.Draw(img)

        # New image for sun/moon overlay
        overlay = Image.new("RGBA", (self.WIDTH, self.HEIGHT), color=(0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        # Draw the sun/moon
        circle = self.circle_coordinates(x, y, self.sun_radius)
        overlay_draw.ellipse(circle, fill=(200, 200, 50, self.opacity))

        # Overlay the sun/moon on the background as an alpha matte
        composite = Image.alpha_composite(img, overlay).filter(
            ImageFilter.GaussianBlur(radius=self.blur)
        )

        return composite

    def overlay_text(
        self, img, position, text, font, align_right=False, rectangle=False
    ):
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
            rect_img = Image.new("RGBA", (self.WIDTH, self.HEIGHT), color=(0, 0, 0, 0))
            rect_draw = ImageDraw.Draw(rect_img)
            rect_draw.rectangle(rect, (255, 255, 255))
            rect_draw.text(position, text, font=font, fill=(0, 0, 0, 0))
            img = Image.alpha_composite(img, rect_img)
        else:
            draw.text(position, text, font=font, fill=(255, 255, 255))
        return img
