# Meteo · a personal weather station

A Flask/MongoDB application for an ESP32 weather station. The station collects
measurements and sends signed JSON. This application stores them and provides a
Ukrainian dashboard, history, rainfall analysis, and an OpenWeather comparison.

The Summer Ocean Breeze interface uses honeydew, frosted blue, cerulean, oxford
navy, and punch red. Fonts and icons are served locally. There is no frontend
framework, build step, CDN dependency, or charting dependency.

## What the interface does

- **Overview:** latest local readings, explicit data age, a 24-hour temperature,
  humidity or pressure chart, hourly rainfall, and the device's air readings.
- **Archive:** 1-, 7-, and 30-day windows, chart metric selection, temperature
  statistics, and a journal of the latest 100 records in the selected window.
  CSV exports those journal records, with UTC timestamps and units in headings.
- **Comparison:** station readings beside OpenWeather **current conditions**,
  absolute differences, and the observation time of each source. It does not
  present the difference as a forecast-accuracy score.
- **Station:** reporting interval, coordinate search or manual coordinates,
  nullable temperature/humidity limits, validation, save, and discard changes.

Charts work with pointer, touch, and keyboard. Focus a chart and use Left/Right,
Home, or End to inspect points. A table alternative accompanies every line chart.
Reduced-motion preferences disable animated transitions.

## Run locally

Python 3.11 or newer is supported. Node 18+ is optional, for JavaScript tests only.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config/config_db.example.py config/config_db.py
Copy-Item .env.example secrets.env
```

Fill `secrets.env` with your MongoDB settings and device credentials, and add an
OpenWeather key if you want external comparison. Existing installations can keep
their current `config/config_db.py`; the redesign does not replace that file.
Keep the HMAC secret and authorization token identical to the ESP32's values.

```powershell
python app.py
```

The default address is `http://localhost:5000/web`. The `PORT` environment variable
can override the default. Other pages are `/web/history`, `/web/comparison`, and
`/web/settings`. Waitress serves the application; Flask's debugger is not enabled.

The existing settings API has no administrator login. Run it behind an access
policy or on a trusted network when configuration changes must be restricted.
This redesign preserves that existing access model.

## Preview without a station or database

```powershell
python -m tools.preview
```

Visit `http://localhost:4302/web`. A visible banner identifies the sample data.
This tool replaces the database and external-weather boundary in memory before
loading the real routes. It never imports private configuration or connects to
MongoDB. Saving settings changes only the preview's memory.

## Tests

```powershell
python -m unittest discover -s tests -v
npm test
npm run check
```

Python tests cover timestamps, rainfall resets/gaps, configuration validation,
bounded query construction, rendering, and signed/unsigned device uploads.
JavaScript tests cover formatting, data freshness, zero values, form conversion,
and CSV output. They require no live services. Query-builder tests use a mock
collection; they do not replace testing aggregation support on your MongoDB.

## Read the code

Start with [the codebase guide](docs/CODEBASE.md). It explains how a reading moves
from the ESP32 to the screen, each module's responsibility, and where to make
common changes. [CONTRIBUTING.md](CONTRIBUTING.md) records the readability standard.

## API compatibility

The ESP32's `POST /api/data` body, `Authorization` header, and `X-Signature` HMAC
verification remain the same. Existing page URLs and data routes remain available.

The dashboard adds `GET /api/data/history?hours=24` (1–720 hours). It returns
time-bucket averages, temperature statistics, and at most 100 recent raw readings.
There are roughly 240 chart buckets per window, rather than every raw record.

Rainfall routes now return `rainfall_mm: null` and `complete: false` when an
interval lacks sufficient coverage or contains a counter reset. Consumers must
distinguish unknown from zero. Hourly queries are limited to 1–168 hours.
Configuration updates validate known fields and preserve unedited nested fields.
`/api/data/stats` and `/api/data/all` remain legacy routes; the new UI uses the
bounded history route instead.

## Data and external sources

- Naive legacy timestamps are interpreted as UTC; explicit offsets are honored.
  The interface displays Europe/Kyiv time, including daylight-saving changes.
- Rainfall keeps the existing calibration: **0.987 mm per tip**. Adjacent counter
  differences are assigned to the later observation's hourly bucket. An interval
  needs a recent baseline and endpoint, no reset, and no gap longer than the
  larger of ten minutes or three configured reporting intervals. The open current
  hour is marked incomplete. Unknown hours are excluded from the displayed sum.
- eCO₂ is shown as a sensor estimate. The device's AQI is not relabelled as a
  standardized regional health index.
- [OpenWeather current conditions](https://openweathermap.org/current) supplies
  external comparison. Its sea-level pressure may differ from local pressure.
- Optional place search uses [Open-Meteo geocoding](https://open-meteo.com/en/docs/geocoding-api),
  with location data from GeoNames. Only an explicit search sends the entered
  place name; entering coordinates works without this service.
- Golos Text is from [Google Fonts](https://github.com/google/fonts/tree/main/ofl/golostext)
  (OFL). Icons are [Lucide](https://lucide.dev/) (ISC). Notices are in `static/licenses/`.

No database migration or new indexes are applied automatically. The compatibility
queries normalize stored strings inside MongoDB; the history range first narrows
the string dates. For a larger archive, a separately planned migration to an
indexed BSON date field will make chronological queries cheaper. Do not migrate
production timestamps without a backup and a compatibility plan for the device.
