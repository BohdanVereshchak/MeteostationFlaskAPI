import { METRICS, formatNumber, formatTimestamp } from "./data.js";
import {
    requestJSON,
    setBusy,
    setConnection,
    setText,
    showNotice,
    startAutoRefresh,
} from "./ui.js";

export function initialize() {
    const refreshButton = document.getElementById("refresh");

    async function refresh() {
        if (refreshButton.disabled) return;
        setBusy(refreshButton, true);
        showNotice();
        try {
            const data = await requestJSON("/api/weather/comparison");
            for (const key of ["temperature", "humidity", "pressure"]) {
                const row = document.querySelector(`[data-comparison="${key}"]`);
                const values = data[key];
                for (const source of ["station", "forecast", "difference"]) {
                    const element = row.querySelector(`[data-source="${source}"]`);
                    const value = values[source];
                    const prefix = source === "difference" && value > 0 ? "+" : "";
                    element.textContent = prefix + formatNumber(value);
                }
                const range = { temperature: 10, humidity: 50, pressure: 50 }[key];
                const position = 50 + Math.max(-1, Math.min(1, values.difference / range)) * 45;
                row.querySelector(".difference-track").style.setProperty(
                    "--position",
                    `${position}%`,
                );
                row.querySelector(".comparison-difference").setAttribute(
                    "aria-label",
                    `Станція мінус OpenWeather: ${formatNumber(values.difference)} ${METRICS[key].unit}`,
                );
            }
            setText("comparison-location", data.location || "Місце не вказано");
            setText("station-time", formatTimestamp(data.timestamp, { year: "numeric" }));
            setText(
                "reference-time",
                data.reference_timestamp
                    ? formatTimestamp(data.reference_timestamp, { year: "numeric" })
                    : "Джерело не надало час",
            );
            setText("reference-description", data.forecast_description || "Опис відсутній");
            setConnection("comparison-status", {
                state: "recent",
                label: "Дані обох джерел завантажено",
            });
        } catch (error) {
            setConnection("comparison-status", { state: "error", label: "Зіставлення недоступне" });
            showNotice(`${error.message} Власні вимірювання можна переглянути в розділі «Огляд».`);
        } finally {
            setBusy(refreshButton, false);
            document.getElementById("comparison-board").setAttribute("aria-busy", "false");
        }
    }

    refreshButton.addEventListener("click", refresh);
    refresh();
    startAutoRefresh(refresh, 300000);
}
