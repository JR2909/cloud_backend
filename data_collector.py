"""
Kontinuierlicher Wetterdaten-Sammler
Ruft OpenWeatherMap-APIs ab und schreibt Ergebnisse in eine SQLite-Datenbank.

Konfiguration:
  .env       -> API_KEY
  CITIES     -> Liste der abzufragenden Städte
  INTERVAL   -> Abfrageintervall in Minuten (Standard: 30)
"""

import sqlite3
import logging
import time
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

load_dotenv()

API_KEY      = os.getenv("API_KEY")
WEATHER_URL  = "http://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

DB_PATH      = Path(__file__).parent / "weather.db"
SCHEMA_PATH  = Path(__file__).parent / "setup_database.sql"

CITIES   = ["Berlin", "München", "Hamburg", "Wien", "Zürich"]
INTERVAL = 30  # Minuten

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "collector.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema nicht gefunden: {SCHEMA_PATH}")
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    log.info("Datenbank initialisiert: %s", DB_PATH)


def upsert_city(conn: sqlite3.Connection, data: dict) -> int:
    conn.execute(
        """
        INSERT INTO cities (name, country, lat, lon, timezone_offset)
        VALUES (:name, :country, :lat, :lon, :timezone_offset)
        ON CONFLICT(name) DO UPDATE SET
            country          = excluded.country,
            lat              = excluded.lat,
            lon              = excluded.lon,
            timezone_offset  = excluded.timezone_offset
        """,
        data,
    )
    row = conn.execute("SELECT id FROM cities WHERE name = ?", (data["name"],)).fetchone()
    return row["id"]


def insert_current(conn: sqlite3.Connection, city_id: int, data: dict) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO weather_current (
            city_id, fetched_at, measured_at,
            temp, feels_like, temp_min, temp_max,
            humidity, pressure,
            weather_main, weather_description, weather_icon,
            wind_speed, wind_deg, clouds, visibility,
            sunrise, sunset
        ) VALUES (
            :city_id, :fetched_at, :measured_at,
            :temp, :feels_like, :temp_min, :temp_max,
            :humidity, :pressure,
            :weather_main, :weather_description, :weather_icon,
            :wind_speed, :wind_deg, :clouds, :visibility,
            :sunrise, :sunset
        )
        """,
        {
            "city_id":             city_id,
            "fetched_at":          now,
            "measured_at":         datetime.fromtimestamp(data["dt"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "temp":                data["main"]["temp"],
            "feels_like":          data["main"]["feels_like"],
            "temp_min":            data["main"]["temp_min"],
            "temp_max":            data["main"]["temp_max"],
            "humidity":            data["main"]["humidity"],
            "pressure":            data["main"]["pressure"],
            "weather_main":        data["weather"][0]["main"],
            "weather_description": data["weather"][0]["description"],
            "weather_icon":        data["weather"][0]["icon"],
            "wind_speed":          data["wind"]["speed"],
            "wind_deg":            data["wind"].get("deg"),
            "clouds":              data["clouds"]["all"],
            "visibility":          data.get("visibility"),
            "sunrise":             datetime.fromtimestamp(data["sys"]["sunrise"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "sunset":              datetime.fromtimestamp(data["sys"]["sunset"],  tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def insert_forecast(conn: sqlite3.Connection, city_id: int, entries: list) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        {
            "city_id":             city_id,
            "fetched_at":          now,
            "forecast_at":         e["dt_txt"],
            "temp":                e["main"]["temp"],
            "feels_like":          e["main"]["feels_like"],
            "temp_min":            e["main"]["temp_min"],
            "temp_max":            e["main"]["temp_max"],
            "humidity":            e["main"]["humidity"],
            "pressure":            e["main"]["pressure"],
            "weather_main":        e["weather"][0]["main"],
            "weather_description": e["weather"][0]["description"],
            "weather_icon":        e["weather"][0]["icon"],
            "wind_speed":          e["wind"]["speed"],
            "wind_deg":            e["wind"].get("deg"),
            "clouds":              e["clouds"]["all"],
            "pop":                 e.get("pop", 0),
        }
        for e in entries
    ]
    conn.executemany(
        """
        INSERT INTO weather_forecast (
            city_id, fetched_at, forecast_at,
            temp, feels_like, temp_min, temp_max,
            humidity, pressure,
            weather_main, weather_description, weather_icon,
            wind_speed, wind_deg, clouds, pop
        ) VALUES (
            :city_id, :fetched_at, :forecast_at,
            :temp, :feels_like, :temp_min, :temp_max,
            :humidity, :pressure,
            :weather_main, :weather_description, :weather_icon,
            :wind_speed, :wind_deg, :clouds, :pop
        )
        """,
        rows,
    )


# ---------------------------------------------------------------------------
# API-Abfragen
# ---------------------------------------------------------------------------

def fetch_current(city: str) -> dict | None:
    try:
        resp = requests.get(
            WEATHER_URL,
            params={"q": city, "appid": API_KEY, "units": "metric", "lang": "de"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.warning("Aktuelles Wetter für '%s' fehlgeschlagen: %s", city, exc)
        return None


def fetch_forecast(city: str) -> list | None:
    try:
        resp = requests.get(
            FORECAST_URL,
            params={"q": city, "appid": API_KEY, "units": "metric", "lang": "de"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("list", [])
    except requests.RequestException as exc:
        log.warning("Vorhersage für '%s' fehlgeschlagen: %s", city, exc)
        return None


# ---------------------------------------------------------------------------
# Sammelrunde
# ---------------------------------------------------------------------------

def collect_once() -> None:
    log.info("Starte Sammelrunde für %d Städte …", len(CITIES))
    with get_connection() as conn:
        for city in CITIES:
            # --- Aktuelles Wetter ---
            current = fetch_current(city)
            if current:
                city_row = {
                    "name":            current["name"],
                    "country":         current["sys"].get("country"),
                    "lat":             current["coord"]["lat"],
                    "lon":             current["coord"]["lon"],
                    "timezone_offset": current.get("timezone"),
                }
                city_id = upsert_city(conn, city_row)
                insert_current(conn, city_id, current)
                log.info("  [OK] Aktuell   %s  %.1f°C", current["name"], current["main"]["temp"])

            # --- Vorhersage ---
            forecast_entries = fetch_forecast(city)
            if forecast_entries and current:
                insert_forecast(conn, city_id, forecast_entries)
                log.info("  [OK] Vorhersage %s  (%d Einträge)", city, len(forecast_entries))

    log.info("Sammelrunde abgeschlossen.")


# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------

def main() -> None:
    if not API_KEY:
        raise SystemExit("Fehler: API_KEY fehlt in der .env-Datei.")

    init_db()
    log.info("Datensammler gestartet | Intervall: %d Minuten | Städte: %s", INTERVAL, ", ".join(CITIES))

    while True:
        collect_once()
        next_run = datetime.now().strftime("%H:%M:%S")
        log.info("Nächste Abfrage in %d Minuten (nächster Lauf ~%s).", INTERVAL,
                 datetime.fromtimestamp(time.time() + INTERVAL * 60).strftime("%H:%M:%S"))
        time.sleep(INTERVAL * 60)


if __name__ == "__main__":
    main()
