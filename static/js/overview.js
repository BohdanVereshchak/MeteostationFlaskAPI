import { createTimeChart } from "./chart.js";
import {
    formatNumber,
    formatTimestamp,
    freshness,
    readingValues,
    thresholdMessage,
} from "./data.js";
import {
    markSelection,
    requestJSON,
    setBusy,
    setConnection,
    setText,
    showNotice,
    startAutoRefresh,
} from "./ui.js";

export function initialize() {
    const chart = createTimeChart(document.getElementById("overview-chart"));
    const refreshButton = document.getElementById("refresh");
    const metricButtons = document.getElementById("overview-metrics");
    const rainButtons = document.getElementById("rain-periods");
    let metric = "temperature";
    let history = { series: [] };
    let rainHours = 24;
    let rainVersion = 0;
    let configuration = {};

    function renderReading(reading) {
        const values = readingValues(reading);
        for (const key of ["temperature", "humidity", "pressure", "aqi", "eco2", "tvoc"]) {
            setText(key, formatNumber(values[key], ["aqi", "eco2", "tvoc"].includes(key) ? 0 : 1));
        }
        const threshold = configuration
            ? thresholdMessage(values.temperature, configuration.temperature)
            : { text: "Межі сповіщень зараз недоступні", warning: false };
        setText("temperature-note", threshold.text);
        document.getElementById("temperature-note").dataset.warning = String(threshold.warning);
        setText("reading-time", formatTimestamp(reading.timestamp, { year: "numeric" }));
        setText("observation-date", "Власна точка спостереження");
        setConnection(
            "station-status",
            freshness(reading.timestamp, configuration?.system?.update_interval_ms),
        );
    }

    function renderRain(report) {
        const container = document.getElementById("rain-chart");
        const available = report.data.filter((point) => point.rainfall_mm !== null);
        const total = available.reduce((sum, point) => sum + point.rainfall_mm, 0);
        const maximum = Math.max(1, ...available.map((point) => point.rainfall_mm));
        setText("rain-total", available.length ? formatNumber(total, 2) : "—");
        const defaultNote = `Дані за ${available.length} з ${report.hours} год. ${available.length < report.hours ? "Штрихування — неповні інтервали; вони не входять у суму." : "Натисніть на стовпчик, щоб побачити вимірювання."}`;
        setText("rain-note", defaultNote);
        container.replaceChildren();
        report.data.forEach((point, index) => {
            const missing = point.rainfall_mm === null;
            const label = `${point.time_label} · ${missing ? "Недостатньо вимірювань" : `${formatNumber(point.rainfall_mm, 2)} мм`}`;
            const button = document.createElement("button");
            button.type = "button";
            button.className = "rain-bar";
            button.dataset.missing = String(missing);
            button.setAttribute("aria-label", label);
            button.style.setProperty(
                "--height",
                `${missing ? 100 : (point.rainfall_mm / maximum) * 100}%`,
            );
            const bar = document.createElement("i");
            bar.setAttribute("aria-hidden", "true");
            button.append(bar);
            if (
                index === 0 ||
                index === report.data.length - 1 ||
                index % Math.ceil(report.hours / 4) === 0
            ) {
                const time = document.createElement("span");
                time.textContent = point.time_label;
                time.setAttribute("aria-hidden", "true");
                button.append(time);
            }
            button.addEventListener("pointerenter", () => setText("rain-note", label));
            button.addEventListener("focus", () => setText("rain-note", label));
            button.addEventListener("click", () => setText("rain-note", label));
            button.addEventListener("blur", () => setText("rain-note", defaultNote));
            button.addEventListener("pointerleave", () => setText("rain-note", defaultNote));
            container.append(button);
        });
    }

    async function loadRain() {
        const version = ++rainVersion;
        try {
            const report = await requestJSON(`/api/data/hourly_rainfall?hours=${rainHours}`);
            if (version === rainVersion) renderRain(report);
        } catch (error) {
            if (version !== rainVersion) return;
            document.getElementById("rain-chart").replaceChildren();
            setText("rain-total", "—");
            setText("rain-note", error.message);
        }
    }

    async function refresh() {
        if (refreshButton.disabled) return;
        setBusy(refreshButton, true);
        showNotice();
        const results = await Promise.allSettled([
            requestJSON("/api/data/last"),
            requestJSON("/api/data/history?hours=24"),
            requestJSON("/api/config"),
            loadRain(),
        ]);
        const [readingResult, historyResult, configurationResult] = results;
        configuration =
            configurationResult.status === "fulfilled" ? configurationResult.value : null;
        if (readingResult.status === "fulfilled" && readingResult.value.length) {
            renderReading(readingResult.value[0]);
        } else {
            setConnection("station-status", {
                state: "error",
                label: "Немає актуального спостереження",
            });
            showNotice(
                readingResult.status === "rejected"
                    ? readingResult.reason.message
                    : "Станція ще не передала вимірювань. Після першого запису вони з’являться тут.",
            );
        }
        if (historyResult.status === "fulfilled") {
            history = historyResult.value;
            setText("overview-chart-note", "Середні значення за інтервалами · останні 24 години");
            chart.update(history.series, metric, history.bucket_seconds);
            const { minimum, maximum } = history.summary;
            setText(
                "temperature-range",
                minimum === undefined || minimum === null
                    ? "—"
                    : `${formatNumber(minimum)} / ${formatNumber(maximum)} °C`,
            );
        } else {
            history = { series: [] };
            chart.update([], metric);
            setText("temperature-range", "—");
            setText("overview-chart-note", historyResult.reason.message);
        }
        document.getElementById("observation-board").setAttribute("aria-busy", "false");
        setBusy(refreshButton, false);
    }

    metricButtons.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-metric]");
        if (!button) return;
        metric = button.dataset.metric;
        markSelection(metricButtons, button);
        chart.update(history.series, metric, history.bucket_seconds);
    });
    rainButtons.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-hours]");
        if (!button) return;
        rainHours = Number(button.dataset.hours);
        markSelection(rainButtons, button);
        loadRain();
    });
    refreshButton.addEventListener("click", refresh);
    refresh();
    startAutoRefresh(refresh, 60000);
}
