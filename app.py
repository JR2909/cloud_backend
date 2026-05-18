import os
import pyodbc
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def get_connection():
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"UID={DB_USER};"
        f"PWD={DB_PASSWORD};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)


def row_to_float(value):
    return float(value) if value is not None else None


@app.route("/")
def health_check():
    return jsonify({
        "status": "running",
        "service": "weather-backend"
    })


@app.route("/api/cities")
def get_cities():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT id, name, country, lat, lon, timezone_offset
        FROM dbo.cities
        ORDER BY name
    """).fetchall()

    conn.close()

    return jsonify([
        {
            "id": row.id,
            "name": row.name,
            "country": row.country,
            "lat": row_to_float(row.lat),
            "lon": row_to_float(row.lon),
            "timezone_offset": row.timezone_offset
        }
        for row in rows
    ])


@app.route("/api/weather/current")
def get_current_weather():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT
            c.name,
            c.country,
            c.lat,
            c.lon,
            c.timezone_offset,
            wc.fetched_at,
            wc.measured_at,
            wc.temp,
            wc.feels_like,
            wc.temp_min,
            wc.temp_max,
            wc.humidity,
            wc.pressure,
            wc.weather_main,
            wc.weather_description,
            wc.weather_icon,
            wc.wind_speed,
            wc.wind_deg,
            wc.clouds,
            wc.visibility,
            wc.sunrise,
            wc.sunset
        FROM dbo.weather_current wc
        JOIN dbo.cities c ON wc.city_id = c.id
        INNER JOIN (
            SELECT city_id, MAX(fetched_at) AS latest_fetch
            FROM dbo.weather_current
            GROUP BY city_id
        ) latest
            ON wc.city_id = latest.city_id
           AND wc.fetched_at = latest.latest_fetch
        ORDER BY c.name
    """).fetchall()

    conn.close()

    return jsonify([
        {
            "name": row.name,
            "country": row.country,
            "coord": {
                "lat": row_to_float(row.lat),
                "lon": row_to_float(row.lon)
            },
            "timezone_offset": row.timezone_offset,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            "measured_at": row.measured_at.isoformat() if row.measured_at else None,
            "temp": row_to_float(row.temp),
            "feels_like": row_to_float(row.feels_like),
            "temp_min": row_to_float(row.temp_min),
            "temp_max": row_to_float(row.temp_max),
            "humidity": row.humidity,
            "pressure": row.pressure,
            "weather_main": row.weather_main,
            "weather_description": row.weather_description,
            "weather_icon": row.weather_icon,
            "wind_speed": row_to_float(row.wind_speed),
            "wind_deg": row.wind_deg,
            "clouds": row.clouds,
            "visibility": row.visibility,
            "sunrise": row.sunrise.isoformat() if row.sunrise else None,
            "sunset": row.sunset.isoformat() if row.sunset else None
        }
        for row in rows
    ])


@app.route("/api/weather/current/<city>")
def get_current_weather_by_city(city):
    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute("""
        SELECT TOP 1
            c.name,
            c.country,
            c.lat,
            c.lon,
            c.timezone_offset,
            wc.fetched_at,
            wc.measured_at,
            wc.temp,
            wc.feels_like,
            wc.temp_min,
            wc.temp_max,
            wc.humidity,
            wc.pressure,
            wc.weather_main,
            wc.weather_description,
            wc.weather_icon,
            wc.wind_speed,
            wc.wind_deg,
            wc.clouds,
            wc.visibility,
            wc.sunrise,
            wc.sunset
        FROM dbo.weather_current wc
        JOIN dbo.cities c ON wc.city_id = c.id
        WHERE LOWER(c.name) = LOWER(?)
        ORDER BY wc.fetched_at DESC
    """, city).fetchone()

    conn.close()

    if not row:
        return jsonify({"error": "city not found"}), 404

    return jsonify({
        "name": row.name,
        "country": row.country,
        "coord": {
            "lat": row_to_float(row.lat),
            "lon": row_to_float(row.lon)
        },
        "timezone_offset": row.timezone_offset,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "measured_at": row.measured_at.isoformat() if row.measured_at else None,
        "temp": row_to_float(row.temp),
        "feels_like": row_to_float(row.feels_like),
        "temp_min": row_to_float(row.temp_min),
        "temp_max": row_to_float(row.temp_max),
        "humidity": row.humidity,
        "pressure": row.pressure,
        "weather_main": row.weather_main,
        "weather_description": row.weather_description,
        "weather_icon": row.weather_icon,
        "wind_speed": row_to_float(row.wind_speed),
        "wind_deg": row.wind_deg,
        "clouds": row.clouds,
        "visibility": row.visibility,
        "sunrise": row.sunrise.isoformat() if row.sunrise else None,
        "sunset": row.sunset.isoformat() if row.sunset else None
    })


@app.route("/api/weather/forecast/<city>")
def get_forecast_by_city(city):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT
            c.name,
            wf.fetched_at,
            wf.forecast_at,
            wf.temp,
            wf.feels_like,
            wf.temp_min,
            wf.temp_max,
            wf.humidity,
            wf.pressure,
            wf.weather_main,
            wf.weather_description,
            wf.weather_icon,
            wf.wind_speed,
            wf.wind_deg,
            wf.clouds,
            wf.pop
        FROM dbo.weather_forecast wf
        JOIN dbo.cities c ON wf.city_id = c.id
        WHERE LOWER(c.name) = LOWER(?)
        ORDER BY wf.forecast_at ASC
    """, city).fetchall()

    conn.close()

    if not rows:
        return jsonify({"error": "forecast not found"}), 404

    return jsonify({
        "city": rows[0].name,
        "forecasts": [
            {
                "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
                "forecast_at": row.forecast_at.isoformat() if row.forecast_at else None,
                "temp": row_to_float(row.temp),
                "feels_like": row_to_float(row.feels_like),
                "temp_min": row_to_float(row.temp_min),
                "temp_max": row_to_float(row.temp_max),
                "humidity": row.humidity,
                "pressure": row.pressure,
                "weather_main": row.weather_main,
                "weather_description": row.weather_description,
                "weather_icon": row.weather_icon,
                "wind_speed": row_to_float(row.wind_speed),
                "wind_deg": row.wind_deg,
                "clouds": row.clouds,
                "pop": row_to_float(row.pop)
            }
            for row in rows
        ]
    })


@app.route("/api/weather/forecast")
def get_all_forecasts():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT
            c.name,
            wf.fetched_at,
            wf.forecast_at,
            wf.temp,
            wf.feels_like,
            wf.temp_min,
            wf.temp_max,
            wf.humidity,
            wf.pressure,
            wf.weather_main,
            wf.weather_description,
            wf.weather_icon,
            wf.wind_speed,
            wf.wind_deg,
            wf.clouds,
            wf.pop
        FROM dbo.weather_forecast wf
        JOIN dbo.cities c ON wf.city_id = c.id
        ORDER BY c.name, wf.forecast_at ASC
    """).fetchall()

    conn.close()

    result = {}

    for row in rows:
        city = row.name

        if city not in result:
            result[city] = {
                "city": city,
                "forecasts": []
            }

        result[city]["forecasts"].append({
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            "forecast_at": row.forecast_at.isoformat() if row.forecast_at else None,
            "temp": row_to_float(row.temp),
            "feels_like": row_to_float(row.feels_like),
            "temp_min": row_to_float(row.temp_min),
            "temp_max": row_to_float(row.temp_max),
            "humidity": row.humidity,
            "pressure": row.pressure,
            "weather_main": row.weather_main,
            "weather_description": row.weather_description,
            "weather_icon": row.weather_icon,
            "wind_speed": row_to_float(row.wind_speed),
            "wind_deg": row.wind_deg,
            "clouds": row.clouds,
            "pop": row_to_float(row.pop)
        })

    return jsonify(list(result.values()))


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "internal server error",
        "details": str(error)
    }), 500


if __name__ == "__main__":
    app.run()