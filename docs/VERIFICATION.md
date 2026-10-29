# Redesign and account verification

Checked on October 29, 2026.

- 32 Python tests passed: time handling, rainfall coverage/reset behavior,
  configuration validation, query scoping, password hashing, exclusive station
  ownership, one-time pairing expiry/reuse, CSRF, session rotation, anonymous
  access, account isolation, and valid/invalid ESP32 uploads.
- Six JavaScript tests passed for numeric/date handling, data age, thresholds,
  form conversion, and CSV. All browser modules passed Node syntax checks.
- Read-only checks against the configured MongoDB successfully ran the new
  latest-reading, history, and rainfall aggregations. No production accounts,
  pairing codes, settings, or sample measurements were written during QA.
- Account CRUD tests use mongomock. They check application behavior and unique
  indexes in an in-memory implementation, rather than proving a deployment's
  MongoDB permissions or multi-process rate-limit configuration.
- Browser QA exercised login/logout, registration, an empty new account, pairing
  an unclaimed device, isolation of the new account's single station, switching
  between an existing account's two stations, authenticated settings saves, zero
  values, invalid ranges, chart metrics, keyboard inspection, and rainfall periods.
- A seven-day CSV downloaded successfully with one header and 100 seven-column
  records. The archive/export explicitly describes that raw-record limit.
- Overview, archive, comparison, station settings, and account station management
  had no document overflow at a 320 CSS-pixel viewport. The archive table scrolls
  inside its own container. Desktop layout was checked at 1309 CSS pixels.
- Screenshots contain isolated sample data. A visible banner identifies them.
  The final source uses finite page/chart animations with reduced-motion checks;
  it no longer opts into the embedded browser's problematic cross-document
  transitions.

No firmware or production weather records were changed. No hosting deployment
command was run. Email verification, automated password recovery, and a shared
distributed request limiter remain outside the current account implementation.
