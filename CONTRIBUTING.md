# Keep the code easy to learn

- Use descriptive names and small functions with one clear responsibility.
- Format Python with four spaces and a 100-character target line length. Keep
  JavaScript, templates, and CSS expanded and consistently indented.
- Prefer plain language features, Flask/Jinja, and native browser APIs. Add a
  dependency when it solves a real problem that the current tools cannot.
- Keep templates structural, page modules focused on their page, and shared
  calculations in pure functions. Avoid duplicate timestamp and numeric rules.
- Comment the reason behind a non-obvious decision. Do not narrate each line,
  retain dead code, or add abstractions for hypothetical future requirements.
- Preserve missing data, units, timestamps, and sensor semantics. Never substitute
  demonstration readings when a real request fails.
- Test changes that affect readings, settings, authentication, time, or exports.
  Use the isolated preview for UI work; do not write test data to the real station.
