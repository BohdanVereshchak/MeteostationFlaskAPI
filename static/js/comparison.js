import { t } from "./i18n.js";
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
                    t("Станція мінус OpenWeather: {difference} {unit}", {
                        difference: formatNumber(values.difference),
                        unit: METRICS[key].unit,
                    }),
                );
            }
            setText("comparison-location", data.location || t("Місце не вказано"));
            setText("station-time", formatTimestamp(data.timestamp, { year: "numeric" }));
            setText(
                "reference-time",
                data.reference_timestamp
                    ? formatTimestamp(data.reference_timestamp, { year: "numeric" })
                    : t("Джерело не надало час"),
            );
            setText("reference-description", data.forecast_description || t("Опис відсутній"));
            setConnection("comparison-status", {
                state: "recent",
                label: t("Дані обох джерел завантажено"),
            });
        } catch (error) {
            setConnection("comparison-status", {
                state: "error",
                label: t("Зіставлення недоступне"),
            });
            showNotice(
                t("{error} Власні вимірювання можна переглянути в розділі «Огляд».", {
                    error: error.message,
                }),
            );
        } finally {
            setBusy(refreshButton, false);
            document.getElementById("comparison-board").setAttribute("aria-busy", "false");
        }
    }

    refreshButton.addEventListener("click", refresh);
    refresh();
    startAutoRefresh(refresh, 300000);
}
