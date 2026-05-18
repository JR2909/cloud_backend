from flask import Flask, render_template, request
from datetime import datetime
import os
from dotenv import load_dotenv

from db import get_connection

app = Flask(__name__)

load_dotenv()

API_KEY = os.getenv("API_KEY")
MAP_API_KEY = os.getenv("MAP_API_KEY")

weatherdata_global = []


@app.template_filter("datetimeformat")
def datetimeformat(value, format="%A, %d.%m."):
    if len(value) == 10:
        dt = datetime.strptime(value, "%Y-%m-%d")
    else:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.strftime(format)


def translate_weather(weather_main):
    translations = {
        "Clear": "Klar",
        "Clouds": "Bewölkt",
        "Rain": "Regen",
        "Snow": "Schnee",
        "Thunderstorm": "Gewitter",
        "Drizzle": "Nieselregen",
        "Mist": "Nebel",
        "Fog": "Nebel"
    }
    return translations.get(weather_main, weather_main)


def get_time_of_day(icon):
    if icon and icon.endswith("n"):
        return "night"
    return "day"


def build_weather_class(weather_main, icon):
    weather_class = weather_main.lower() if weather_main else "clouds"
    time_of_day = get_time_of_day(icon)
    return f"{weather_class}-{time_of_day}"


@app.route("/", methods=["GET", "POST"])
def home():
    global weatherdata_global

    weatherdata = []

    if request.method == "POST":
        conn = get_connection()
        cursor = conn.cursor()

        for i in range(1, 4):
            stadt = request.form.get(f"stadt{i}")

            if not stadt:
                continue

            row = cursor.execute("""
                SELECT TOP 1
                    c.name,
                    c.lat,
                    c.lon,
                    wc.fetched_at,
                    wc.measured_at,
                    wc.temp,
                    wc.feels_like,
                    wc.temp_min,
                    wc.temp_max,
                    wc.humidity,
                    wc.weather_main,
                    wc.weather_description,
                    wc.weather_icon,
                    wc.sunrise,
                    wc.sunset
                FROM dbo.weather_current wc
                JOIN dbo.cities c ON wc.city_id = c.id
                WHERE LOWER(c.name) = LOWER(?)
                ORDER BY wc.fetched_at DESC
            """, stadt).fetchone()

            if row:
                weather_main = row.weather_main
                icon = row.weather_icon

                weatherdata.append({
                    "name": row.name,
                    "icon": icon,
                    "weather": weather_main,
                    "description": row.weather_description,
                    "temp": round(float(row.temp), 1),
                    "feels_like": round(float(row.feels_like), 1),
                    "temp_min": round(float(row.temp_min), 1),
                    "temp_max": round(float(row.temp_max), 1),
                    "humidity": row.humidity,
                    "sunrise": row.sunrise.strftime("%H:%M") + " Uhr" if row.sunrise else "-",
                    "sunset": row.sunset.strftime("%H:%M") + " Uhr" if row.sunset else "-",
                    "messzeit": row.measured_at.strftime("%d.%m.%Y %H:%M") if row.measured_at else "-",
                    "weather_class": build_weather_class(weather_main, icon),
                    "weather_ger": translate_weather(weather_main),
                    "local_time": datetime.now().strftime("%H:%M") + " Uhr",
                    "coord": {
                        "lat": float(row.lat),
                        "lon": float(row.lon)
                    }
                })
            else:
                weatherdata.append({
                    "name": stadt,
                    "error": "Keine Wetterdaten gefunden"
                })

        conn.close()

    weatherdata_global = weatherdata

    return render_template("index.html", weatherdata=weatherdata)


@app.route("/karte")
def map():
    if not weatherdata_global:
        return "Bitte zuerst Städte auf der Startseite eingeben.", 400

    safe_weatherdata = []

    for city in weatherdata_global:
        safe_weatherdata.append({
            "name": city.get("name", "Unbekannt"),
            "coord": city.get("coord", {"lat": 0, "lon": 0}),
            "weather_ger": city.get("weather_ger", "Unbekannt"),
            "description": city.get("description", ""),
            "temp": city.get("temp", 0),
            "humidity": city.get("humidity", 0),
            "icon": city.get("icon", "01d"),
            "weather_class": city.get("weather_class", "clouds-day"),
            "error": city.get("error")
        })

    return render_template(
        "map.html",
        weatherdata=safe_weatherdata,
        api_key=API_KEY,
        map_key=MAP_API_KEY
    )


@app.route("/vorhersage")
def forecast():
    if not weatherdata_global:
        return "Bitte zuerst Städte auf der Startseite eingeben.", 400

    conn = get_connection()
    cursor = conn.cursor()

    forecastdata = []

    for city in weatherdata_global:
        if city.get("error"):
            continue

        rows = cursor.execute("""
            SELECT
                wf.forecast_at,
                wf.temp,
                wf.humidity,
                wf.weather_description,
                wf.weather_icon,
                wf.wind_speed
            FROM dbo.weather_forecast wf
            JOIN dbo.cities c ON wf.city_id = c.id
            WHERE LOWER(c.name) = LOWER(?)
            ORDER BY wf.forecast_at ASC
        """, city["name"]).fetchall()

        forecasts = []

        for row in rows:
            forecasts.append({
                "timestamp": row.forecast_at.strftime("%Y-%m-%d %H:%M:%S"),
                "temp": round(float(row.temp), 1),
                "description": row.weather_description,
                "icon": row.weather_icon,
                "humidity": row.humidity,
                "wind": round(float(row.wind_speed), 1)
            })

        forecastdata.append({
            "city": city["name"],
            "forecasts": forecasts
        })

    conn.close()

    return render_template("forecast.html", forecastdata=forecastdata)


if __name__ == "__main__":
    app.run(debug=True)