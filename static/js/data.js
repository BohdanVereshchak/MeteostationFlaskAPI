export const METRICS = {
    temperature: { label: "Температура", unit: "°C", digits: 1 },
    humidity: { label: "Вологість", unit: "%", digits: 1 },
    pressure: { label: "Тиск", unit: "гПа", digits: 1 },
    eco2: { label: "eCO₂", unit: "ppm", digits: 0 },
    tvoc: { label: "TVOC", unit: "ppb", digits: 0 },
    aqi: { label: "AQI", unit: "", digits: 0 },
};

export function numberOrNull(value) {
    if (value === null || value === undefined || typeof value === "boolean") return null;
    if (typeof value === "string" && !value.trim()) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

export function formatNumber(value, digits = 1) {
    const number = numberOrNull(value);
    return number === null
        ? "—"
        : new Intl.NumberFormat("uk-UA", {
              minimumFractionDigits: digits,
              maximumFractionDigits: digits,
          }).format(number);
}

export function parseTimestamp(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    let timestamp = value.trim().replace(" ", "T");
    if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(timestamp)) timestamp += "Z";
    const date = new Date(timestamp);
    return Number.isNaN(date.getTime()) ? null : date;
}

export function formatTimestamp(value, options = {}) {
    const date = value instanceof Date ? value : parseTimestamp(value);
    if (!date) return "Час не вказано";
    return new Intl.DateTimeFormat("uk-UA", {
        timeZone: "Europe/Kyiv",
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        ...options,
    }).format(date);
}

export function readingValues(reading) {
    return {
        timestamp: reading.timestamp,
        temperature: numberOrNull(reading.environment?.temperature),
        humidity: numberOrNull(reading.environment?.humidity),
        pressure: numberOrNull(reading.environment?.pressure),
        eco2: numberOrNull(reading.air_quality?.eco2),
        tvoc: numberOrNull(reading.air_quality?.tvoc),
        aqi: numberOrNull(reading.air_quality?.aqi),
    };
}

export function freshness(timestamp, intervalMs = 60000, now = Date.now()) {
    const date = parseTimestamp(timestamp);
    if (!date) return { state: "error", label: "Час вимірювання невідомий" };
    const age = now - date.getTime();
    if (age < -60000) return { state: "error", label: "Перевірте годинник станції" };
    const minutes = Math.max(0, Math.floor(age / 60000));
    const stale = age > Math.max(300000, intervalMs * 3);
    const ago = minutes < 1 ? "менше хвилини тому" : `${formatNumber(minutes, 0)} хв тому`;
    return {
        state: stale ? "stale" : "recent",
        label: `${stale ? "Дані застаріли" : "Отримано"} · ${ago}`,
    };
}

export function thresholdMessage(value, limits) {
    const number = numberOrNull(value);
    if (number === null) return { text: "Немає показника температури", warning: false };
    const minimum = numberOrNull(limits?.min);
    const maximum = numberOrNull(limits?.max);
    if (minimum !== null && number < minimum)
        return { text: `Нижче встановленої межі ${formatNumber(minimum)} °C`, warning: true };
    if (maximum !== null && number > maximum)
        return { text: `Вище встановленої межі ${formatNumber(maximum)} °C`, warning: true };
    return {
        text:
            minimum === null && maximum === null
                ? "Локальне спостереження станції"
                : "У межах ваших налаштувань",
        warning: false,
    };
}

export function configurationFromForm(form) {
    const fields = new FormData(form);
    const value = (name) => numberOrNull(fields.get(name));
    const configuration = {
        system: { update_interval_ms: value("update_interval") * 1000 },
        location: { latitude: value("latitude"), longitude: value("longitude") },
        temperature: { min: value("temperature_min"), max: value("temperature_max") },
        humidity: { min: value("humidity_min"), max: value("humidity_max") },
    };
    for (const name of ["temperature", "humidity"]) {
        const limits = configuration[name];
        if (limits.min !== null && limits.max !== null && limits.min > limits.max) {
            const label = name === "temperature" ? "температури" : "вологості";
            throw new Error(`Нижня межа ${label} не може перевищувати верхню.`);
        }
    }
    return configuration;
}

export function csvDocument(readings) {
    const columns = [
        "timestamp_utc",
        "temperature_c",
        "humidity_percent",
        "pressure_hpa",
        "eco2_ppm",
        "tvoc_ppb",
        "sensor_aqi",
    ];
    const escape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const rows = readings.map((reading) => {
        const values = readingValues(reading);
        const timestamp = parseTimestamp(values.timestamp)?.toISOString() ?? "";
        return [
            timestamp,
            values.temperature,
            values.humidity,
            values.pressure,
            values.eco2,
            values.tvoc,
            values.aqi,
        ]
            .map(escape)
            .join(",");
    });
    return "\uFEFF" + [columns.join(","), ...rows].join("\r\n");
}
