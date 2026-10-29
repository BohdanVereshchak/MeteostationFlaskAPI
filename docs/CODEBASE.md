# Reading and changing Meteo

## Follow one reading

1. The ESP32 creates its JSON and signs the exact bytes with HMAC SHA-256.
2. `receive_data()` in `app.py` checks the authorization token and signature.
   It adds the mapped device ID, checks configured thresholds, and stores the
   reading in MongoDB. The redesign keeps that upload contract.
3. Read routes call helpers in `weather_data.py`. This is where timestamp formats,
   bounded history windows, aggregation, and rainfall-counter differences belong.
4. Flask renders a page from `templates/`. Templates describe structure and labels;
   they contain no fetching, arithmetic, or inline scripts.
5. `static/js/main.js` loads the module matching the page's `data-page` value.
   That page module requests JSON, uses shared formatting, and updates the DOM.

```text
ESP32 → signed POST → app.py → MongoDB
                                 ↓
Browser ← page module ← JSON ← weather_data.py
```

## File responsibilities

| File | Responsibility |
| --- | --- |
| `app.py` | Flask setup, HTTP routes, upload authentication, external-weather calls |
| `accounts.py` | User hashes, station ownership, per-device settings, one-time pairing codes |
| `auth.py` | Session/CSRF boundaries, account routes, station selection, scoped request context |
| `weather_data.py` | Query building, timestamp normalization, rainfall logic, configuration validation |
| `templates/base.html` | Shared document, navigation, icon macro, footer |
| `templates/index.html` | Current observation, daily trend, rainfall, air readings |
| `templates/history.html` | Archive controls, statistics, journal |
| `templates/comparison.html` | Side-by-side external comparison |
| `templates/settings.html` | Labelled native form and save/reset controls |
| `static/css/station.css` | Palette tokens, components, responsive rules, reduced motion |
| `static/js/data.js` | Pure formatting, timestamp parsing, freshness, form conversion, CSV |
| `static/js/ui.js` | Small DOM helpers, timed JSON requests, visible-page polling |
| `static/js/chart.js` | SVG chart, gaps, pointer/keyboard inspection, table alternative |
| `static/js/overview.js` | Overview data loading and rainfall controls |
| `static/js/history.js` | Window/metric selection, journal, CSV download |
| `static/js/comparison.js` | Compare sources and their observation times |
| `static/js/settings.js` | Populate, validate, save/reset, optional place search |
| `tools/demo_data.py` | Explicit in-memory sample data and service replacements for local QA |
| `tests/` | Offline regressions for behavior that can break real readings |

## Why these boundaries exist

**Keep arithmetic out of templates.** The server decides what a rainfall total
means. The browser formats a value; it should not invent a missing measurement.

**Keep data formatting testable without the page.** `data.js` has no dependency on
DOM selectors. For example, `numberOrNull(0)` stays zero and `freshness()` accepts
a clock argument, so tests do not depend on when they run.

**Keep browser requests recoverable.** `requestJSON()` times out and produces an
actionable message. Archive and rainfall requests carry a sequence number so a
slow earlier response cannot replace a newer filter selection. Polling pauses
while the document is hidden and avoids overlapping automatic updates.

**Treat unknown as a value of its own.** A dry hour has a numeric zero. A missing
rain baseline, long reporting gap, or counter reset produces `null`. Charts
leave gaps; they do not draw a continuous line across missing time buckets.

**Use native controls first.** Forms have actual labels and number inputs. Chart
points use one tab stop with arrow navigation; a table exposes the same values.
Navigation is made of real links, so history, new tabs, and no-animation fallbacks
remain available.

## Common changes

- **Change colors or type:** edit `:root` and `@font-face` in `station.css`.
- **Add a measurement:** extend the server history aggregation, `METRICS` and
  `readingValues()` in `data.js`, then the relevant template and page module.
- **Change reporting limits:** edit both native input bounds and
  `validate_configuration()`. The server must validate even if the browser does.
- **Change rainfall calibration:** update `RAIN_MM_PER_TIP` after calibrating the
  sensor. Update the documented factor and tests together.
- **Change a trend window:** keep the server's 720-hour maximum and chart-bucket
  budget in mind. Raw-record export currently means the latest 100 journal rows.
- **Add a page:** add a Flask route, extend `base.html`, and add a page-module
  loader in `main.js`. Shared helpers should stay small rather than becoming a
  general component framework.

## Before sharing changes

Run the Python tests and the two npm scripts. Use the isolated preview to check
desktop, narrow screens, keyboard controls, and reduced motion. Use your actual
MongoDB for read-only integration checks when query logic changes; fixtures do
not prove database behavior. Do not submit sample readings to the live device
endpoint or save test settings against production.

Configuration and private keys stay local. Ignoring or untracking an existing
file does not remove earlier commits; rotate exposed credentials and review
repository history separately before distributing it.

## Follow an authenticated request

`install_authentication()` installs a request guard. It resolves the session's
user ID, loads only stations owned by that user, and resolves the selected station
again on the server. It rejects anonymous API reads and browser writes without a
matching CSRF code. The template receives `g.user`, `g.stations`, and `g.station`;
no password hash or device token is put into the session cookie.

A chart route calls `active_data_filter()` and passes that filter to the query
helper. The filter goes at the beginning of every aggregation, before summaries
or rainfall baselines are calculated. Filtering the final display would be too
late: aggregates could already contain another device's readings.

Device requests take a separate path. A signed upload maps its token to the
configured device ID, ignoring any claimed ID in the payload. Token-bearing
configuration requests read that device's settings. They do not acquire a
browser session and cannot read the browser's historical-data endpoints.

The operator's pairing tool issues a random 128-bit code, stores only its digest
and expiry, and reveals the code once. Redemption uses MongoDB's atomic
`find_one_and_delete()`, so only one claimant can consume it. A unique device ID
index still prevents a concurrent claim from replacing an existing owner. If a
server error interrupts connection after consumption, issue a fresh code; do not
make a consumed code reusable.

The indexes are additive. Tests use `mongomock` for account persistence and
explicitly replace sensor-query boundaries in the preview. Production never
imports the preview account or sample readings. The original station data remains
in its existing collection; ownership is represented in separate collections.
