import requests


def aqi_to_color(aqi):
    """Return a color based on AQI value."""
    if 0 <= aqi <= 50:
        return (0, 128, 0)  # Green
    elif 51 <= aqi <= 100:
        return (192, 192, 0)  # Yellow
    elif 101 <= aqi <= 150:
        return (192, 128, 0)  # Orange
    elif 151 <= aqi <= 200:
        return (192, 0, 0)  # Red
    elif 201 <= aqi <= 300:
        return (128, 0, 128)  # Purple
    elif 301 <= aqi <= 500:
        return (128, 0, 0)  # Maroon
    else:
        return (0, 0, 0)  # Default to black for invalid AQI values


def describe_aqi(aqi: float) -> str:
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


def get_external_AQI(latitude: str, longitude: str, waqi_api_key: str) -> int:
    # Set the API endpoint and parameters
    url = f"https://api.waqi.info/feed/geo:{latitude};{longitude}/?token={waqi_api_key}"

    # Send the request and get the response

    # Check if the request was successful
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if response.status_code == 200:
            return int(data["data"]["aqi"])
        print("Error:", data["data"])
        return -1
    except Exception as e:
        print(f"Failed to retrieve AQI. {e}")
        return -1
