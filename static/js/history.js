import { createTimeChart } from "./chart.js";
import { csvDocument, formatNumber, formatTimestamp, readingValues } from "./data.js";
import { appendCells, markSelection, requestJSON, setText, showNotice } from "./ui.js";

export function initialize() {
    const chart = createTimeChart(document.getElementById("history-chart"));
    const period = document.getElementById("history-period");
    const buttons = document.getElementById("history-metrics");
    const exportButton = document.getElementById("export");
    let metric = "temperature";
    let report = { series: [], readings: [] };
    let requestVersion = 0;

    function renderRows() {
        const body = document.getElementById("history-rows");
        body.replaceChildren();
        for (const record of report.readings) {
            const reading = readingValues(record);
            appendCells(body.insertRow(), [
                formatTimestamp(record.timestamp, { year: "numeric", second: "2-digit" }),
                formatNumber(reading.temperature),
                formatNumber(reading.humidity),
                formatNumber(reading.pressure),
                formatNumber(reading.eco2, 0),
                formatNumber(reading.tvoc, 0),
                formatNumber(reading.aqi, 0),
            ]);
        }
        if (!report.readings.length) {
            const cell = body.insertRow().insertCell();
            cell.colSpan = 7;
            cell.textContent = "У цьому періоді вимірювань немає. Оберіть інший період.";
        }
        setText("log-count", `${report.readings.length} із ${report.summary?.count ?? 0} записів`);
        exportButton.disabled = !report.readings.length;
        exportButton.title = "Окремі вимірювання з журналу (до 100 записів)";
    }

    async function loadHistory() {
        const version = ++requestVersion;
        exportButton.disabled = true;
        showNotice();
        try {
            const response = await requestJSON(`/api/data/history?hours=${period.value}`);
            if (version !== requestVersion) return;
            report = response;
            chart.update(report.series, metric, report.bucket_seconds);
            for (const key of ["average", "minimum", "maximum", "count"]) {
                setText(
                    `summary-${key}`,
                    formatNumber(report.summary[key], key === "count" ? 0 : 1),
                );
            }
            setText(
                "history-caption",
                `Крок графіка: ${formatNumber(report.bucket_seconds / 60, 0)} хв. Графік показує середні значення; прогалини не з’єднуються. Журнал і CSV містять до 100 останніх окремих вимірювань.`,
            );
            renderRows();
        } catch (error) {
            if (version !== requestVersion) return;
            report = { series: [], readings: [] };
            chart.update([], metric);
            ["average", "minimum", "maximum", "count"].forEach((key) =>
                setText(`summary-${key}`, "—"),
            );
            renderRows();
            showNotice(error.message);
        }
    }

    buttons.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-metric]");
        if (!button) return;
        metric = button.dataset.metric;
        markSelection(buttons, button);
        chart.update(report.series, metric, report.bucket_seconds);
    });
    period.addEventListener("change", loadHistory);
    exportButton.addEventListener("click", () => {
        const file = new Blob([csvDocument(report.readings)], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(file);
        const link = document.createElement("a");
        link.href = url;
        link.download = `meteo-${period.value}h-latest-readings.csv`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    loadHistory();
}
