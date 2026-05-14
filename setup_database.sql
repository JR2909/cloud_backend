-- =============================================================
-- Datenbankschema für Wetterdaten (OpenWeatherMap)
-- SQLite-kompatibel
-- =============================================================

CREATE TABLE IF NOT EXISTS cities (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL UNIQUE,
    country          TEXT,
    lat              REAL,
    lon              REAL,
    timezone_offset  INTEGER
);

-- Aktuelle Wettermessungen
CREATE TABLE IF NOT EXISTS weather_current (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id             INTEGER NOT NULL,
    fetched_at          TEXT    NOT NULL,   -- UTC-Zeitpunkt des API-Abrufs
    measured_at         TEXT    NOT NULL,   -- Messzeitpunkt laut API (UTC)
    temp                REAL,
    feels_like          REAL,
    temp_min            REAL,
    temp_max            REAL,
    humidity            INTEGER,
    pressure            INTEGER,
    weather_main        TEXT,
    weather_description TEXT,
    weather_icon        TEXT,
    wind_speed          REAL,
    wind_deg            INTEGER,
    clouds              INTEGER,
    visibility          INTEGER,
    sunrise             TEXT,
    sunset              TEXT,
    FOREIGN KEY (city_id) REFERENCES cities(id)
);

-- 5-Tage-Vorhersage (3-Stunden-Intervalle)
CREATE TABLE IF NOT EXISTS weather_forecast (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id             INTEGER NOT NULL,
    fetched_at          TEXT    NOT NULL,   -- UTC-Zeitpunkt des API-Abrufs
    forecast_at         TEXT    NOT NULL,   -- Vorhersagezeitpunkt (UTC)
    temp                REAL,
    feels_like          REAL,
    temp_min            REAL,
    temp_max            REAL,
    humidity            INTEGER,
    pressure            INTEGER,
    weather_main        TEXT,
    weather_description TEXT,
    weather_icon        TEXT,
    wind_speed          REAL,
    wind_deg            INTEGER,
    clouds              INTEGER,
    pop                 REAL,              -- Niederschlagswahrscheinlichkeit (0-1)
    FOREIGN KEY (city_id) REFERENCES cities(id)
);

-- Indizes für schnelle Zeitbereichsabfragen
CREATE INDEX IF NOT EXISTS idx_current_city_time
    ON weather_current(city_id, measured_at);

CREATE INDEX IF NOT EXISTS idx_forecast_city_time
    ON weather_forecast(city_id, forecast_at);
