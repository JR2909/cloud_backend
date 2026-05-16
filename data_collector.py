import re
import logging
import time
import os
from datetime import datetime, timezone
from pathlib import Path

import pyodbc
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

load_dotenv()

API_KEY      = os.getenv("API_KEY")
WEATHER_URL  = "http://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

DB_SERVER   = os.getenv("DB_SERVER")
DB_NAME     = os.getenv("DB_NAME")
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

SCHEMA_PATH = Path(__file__).parent / "setup_database.sql"

CITIES   = ["Berlin", "Heilbronn", "Hamburg", "Wien", "Zürich"]
INTERVAL = 360  # Minuten

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

def get_connection() -> pyodbc.Connection:
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"UID={DB_USER};"
        f"PWD={DB_PASSWORD};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    conn = pyodbc.connect(conn_str)
    conn.autocommit = False
    return conn


def init_db() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema nicht gefunden: {SCHEMA_PATH}")
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    # GO ist der T-SQL Batch-Trenner; pyodbc versteht ihn nicht direkt
    statements = [s.strip() for s in re.split(r"^\s*GO\s*$", sql, flags=re.MULTILINE) if s.strip()]
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for stmt in statements:
            cursor.execute(stmt)
        conn.commit()
        log.info("Datenbank initialisiert: %s / Schema: dbo", DB_NAME)
    finally:
        conn.close()


def upsert_city(cursor: pyodbc.Cursor, data: dict) -> int:
    cursor.execute(
        """
        MERGE dbo.cities AS target
        USING (SELECT ? AS name, ? AS country, ? AS lat, ? AS lon, ? AS timezone_offset) AS source
        ON target.name = source.name
        WHEN MATCHED THEN
            UPDATE SET
                country         = source.country,
                lat             = source.lat,
                lon             = source.lon,
                timezone_offset = source.timezone_offset
        WHEN NOT MATCHED THEN
            INSERT (name, country, lat, lon, timezone_offset)
            VALUES (source.name, source.country, source.lat, source.lon, source.timezone_offset);
        """,
        (data["name"], data["country"], data["lat"], data["lon"], data["timezone_offset"]),
    )
    row = cursor.execute("SELECT id FROM dbo.cities WHERE name = ?", (data["name"],)).fetchone()
    return row[0]


def insert_current(cursor: pyodbc.Cursor, city_id: int, data: dict) -> None:
    now      = datetime.now(timezone.utc)
    measured = datetime.fromtimestamp(data["dt"], tz=timezone.utc)
    sunrise  = datetime.fromtimestamp(data["sys"]["sunrise"], tz=timezone.utc)
    sunset   = datetime.fromtimestamp(data["sys"]["sunset"],  tz=timezone.utc)

    cursor.execute(
        """
        INSERT INTO dbo.weather_current (
            city_id, fetched_at, measured_at,
            temp, feels_like, temp_min, temp_max,
            humidity, pressure,
            weather_main, weather_description, weather_icon,
            wind_speed, wind_deg, clouds, visibility,
            sunrise, sunset
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            city_id, now, measured,
            data["main"]["temp"],     data["main"]["feels_like"],
            data["main"]["temp_min"], data["main"]["temp_max"],
            data["main"]["humidity"], data["main"]["pressure"],
            data["weather"][0]["main"], data["weather"][0]["description"], data["weather"][0]["icon"],
            data["wind"]["speed"], data["wind"].get("deg"),
            data["clouds"]["all"], data.get("visibility"),
            sunrise, sunset,
        ),
    )


def insert_forecast(cursor: pyodbc.Cursor, city_id: int, entries: list) -> None:
    now = datetime.now(timezone.utc)
    rows = []
    for e in entries:
        forecast_at = datetime.strptime(e["dt_txt"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        rows.append((
            city_id, now, forecast_at,
            e["main"]["temp"],     e["main"]["feels_like"],
            e["main"]["temp_min"], e["main"]["temp_max"],
            e["main"]["humidity"], e["main"]["pressure"],
            e["weather"][0]["main"], e["weather"][0]["description"], e["weather"][0]["icon"],
            e["wind"]["speed"], e["wind"].get("deg"),
            e["clouds"]["all"], e.get("pop", 0),
        ))

    cursor.executemany(
        """
        INSERT INTO dbo.weather_forecast (
            city_id, fetched_at, forecast_at,
            temp, feels_like, temp_min, temp_max,
            humidity, pressure,
            weather_main, weather_description, weather_icon,
            wind_speed, wind_deg, clouds, pop
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for city in CITIES:
            current = fetch_current(city)
            if current:
                city_row = {
                    "name":            current["name"],
                    "country":         current["sys"].get("country"),
                    "lat":             current["coord"]["lat"],
                    "lon":             current["coord"]["lon"],
                    "timezone_offset": current.get("timezone"),
                }
                city_id = upsert_city(cursor, city_row)
                insert_current(cursor, city_id, current)
                log.info("  [OK] Aktuell   %s  %.1f°C", current["name"], current["main"]["temp"])

            forecast_entries = fetch_forecast(city)
            if forecast_entries and current:
                insert_forecast(cursor, city_id, forecast_entries)
                log.info("  [OK] Vorhersage %s  (%d Einträge)", city, len(forecast_entries))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    log.info("Sammelrunde abgeschlossen.")


# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------

def main() -> None:
    if not API_KEY:
        raise SystemExit("Fehler: API_KEY fehlt in der .env-Datei.")
    if not all([DB_SERVER, DB_NAME, DB_USER, DB_PASSWORD]):
        raise SystemExit("Fehler: Datenbankverbindungsdaten (DB_SERVER, DB_NAME, DB_USER, DB_PASSWORD) fehlen.")

    init_db()
    log.info("Datensammler gestartet | Intervall: %d Minuten | Städte: %s", INTERVAL, ", ".join(CITIES))

    while True:
        collect_once()
        log.info("Nächste Abfrage in %d Minuten (nächster Lauf ~%s).", INTERVAL,
                 datetime.fromtimestamp(time.time() + INTERVAL * 60).strftime("%H:%M:%S"))
        time.sleep(INTERVAL * 60)


if __name__ == "__main__":
    main()
