import test from "node:test";
import assert from "node:assert/strict";
import {
    configurationFromForm,
    csvDocument,
    freshness,
    numberOrNull,
    parseTimestamp,
    readingValues,
    thresholdMessage,
} from "../static/js/data.js";

test("zero is a measurement; empty, non-finite, and boolean values are not", () => {
    assert.equal(numberOrNull(0), 0);
    for (const value of [null, undefined, "", Infinity, NaN, true])
        assert.equal(numberOrNull(value), null);
    assert.equal(readingValues({ environment: { temperature: 0 } }).temperature, 0);
});

test("legacy UTC and explicit-offset timestamps describe the same instant", () => {
    const expected = "2026-10-29T10:00:00.000Z";
    for (const value of [
        "2026-10-29 10:00:00",
        "2026-10-29T10:00:00Z",
        "2026-10-29T12:00:00+02:00",
    ]) {
        assert.equal(parseTimestamp(value).toISOString(), expected);
    }
    assert.equal(parseTimestamp("not a timestamp"), null);
});

test("freshness distinguishes delayed sensor data and future clocks", () => {
    const now = Date.parse("2026-10-29T10:10:00Z");
    assert.equal(freshness("2026-10-29T10:09:00Z", 60000, now).state, "recent");
    assert.equal(freshness("2026-10-29T09:00:00Z", 60000, now).state, "stale");
    assert.equal(freshness("2026-10-29T11:00:00Z", 60000, now).state, "error");
    assert.equal(freshness(null, 60000, now).state, "error");
});

test("temperature threshold zero is not replaced by a default", () => {
    assert.equal(thresholdMessage(-1, { min: 0, max: 20 }).warning, true);
    assert.equal(thresholdMessage(0, { min: 0, max: 20 }).warning, false);
    assert.equal(thresholdMessage(22, {}).warning, false);
});

test("settings preserve zero coordinates and disabled bounds", () => {
    const NativeFormData = globalThis.FormData;
    globalThis.FormData = class {
        constructor(values) {
            this.values = values;
        }
        get(key) {
            return this.values[key] ?? "";
        }
    };
    try {
        const values = {
            update_interval: "60",
            latitude: "0",
            longitude: "0",
            temperature_min: "0",
            temperature_max: "",
            humidity_min: "0",
            humidity_max: "100",
        };
        const configuration = configurationFromForm(values);
        assert.equal(configuration.location.latitude, 0);
        assert.equal(configuration.temperature.min, 0);
        assert.equal(configuration.temperature.max, null);
        assert.equal(configuration.system.update_interval_ms, 60000);
        assert.throws(
            () =>
                configurationFromForm({ ...values, temperature_min: "25", temperature_max: "20" }),
            /Нижня межа/,
        );
    } finally {
        globalThis.FormData = NativeFormData;
    }
});

test("CSV has UTC times, stable columns, numeric zero, and empty missing readings", () => {
    const csv = csvDocument([
        { timestamp: "2026-10-29 10:00:00", environment: { temperature: 0, humidity: 50 } },
    ]);
    assert.ok(csv.includes("timestamp_utc,temperature_c"));
    assert.ok(csv.includes('"2026-10-29T10:00:00.000Z","0","50","","","",""'));
    assert.equal(csv.includes("undefined"), false);
});
