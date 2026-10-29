import { t, language } from "./i18n.js";
import { configurationFromForm, numberOrNull } from "./data.js";
import { requestJSON, setBusy, setText, showNotice } from "./ui.js";

export function initialize() {
    const form = document.getElementById("station-form");
    const saveButton = document.getElementById("save-settings");
    const resetButton = document.getElementById("reset-settings");
    const interval = document.getElementById("update-interval");
    const searchInput = document.getElementById("location-search");
    const searchButton = document.getElementById("search-location");
    const results = document.getElementById("location-results");
    let savedConfiguration = null;
    let pending = false;

    function setSaveStatus(message, state = "") {
        setText("save-status", message);
        document.getElementById("save-status").dataset.state = state;
    }

    function updatePresets() {
        form.querySelectorAll("[data-interval]").forEach((button) => {
            button.setAttribute(
                "aria-pressed",
                String(Number(button.dataset.interval) === Number(interval.value)),
            );
        });
    }

    function populate(configuration) {
        interval.value = (configuration.system?.update_interval_ms ?? 60000) / 1000;
        document.getElementById("latitude").value = configuration.location?.latitude ?? 49.8815;
        document.getElementById("longitude").value = configuration.location?.longitude ?? 24.0929;
        for (const metric of ["temperature", "humidity"]) {
            for (const limit of ["min", "max"]) {
                document.getElementById(`${metric}-${limit}`).value =
                    configuration[metric]?.[limit] ?? "";
            }
        }
        updatePresets();
    }

    async function loadConfiguration() {
        try {
            savedConfiguration = await requestJSON("/api/config");
            populate(savedConfiguration);
            setSaveStatus(t("Поточні налаштування завантажено"));
        } catch (error) {
            if (error.status === 404) {
                savedConfiguration = {};
                populate({});
                setSaveStatus(t("Налаштуйте станцію вперше"));
            } else {
                showNotice(error.message);
                setSaveStatus(t("Не вдалося завантажити конфігурацію. Оновіть сторінку."), "error");
                return;
            }
        }
        saveButton.disabled = false;
        resetButton.disabled = false;
    }

    async function searchLocation() {
        const query = searchInput.value.trim();
        if (query.length < 2) {
            results.textContent = t("Введіть щонайменше дві літери.");
            return;
        }
        setBusy(searchButton, true);
        results.textContent = t("Шукаємо населений пункт…");
        try {
            const parameters = new URLSearchParams({
                name: query,
                count: 4,
                language,
                format: "json",
            });
            const data = await requestJSON(
                `https://geocoding-api.open-meteo.com/v1/search?${parameters}`,
            );
            results.replaceChildren();
            if (!data.results?.length) {
                results.textContent = t(
                    "Нічого не знайдено. Введіть іншу назву або координати вручну.",
                );
                return;
            }
            for (const location of data.results) {
                const button = document.createElement("button");
                button.type = "button";
                button.textContent = [location.name, location.admin1, location.country]
                    .filter(Boolean)
                    .join(", ");
                button.addEventListener("click", () => {
                    document.getElementById("latitude").value = location.latitude;
                    document.getElementById("longitude").value = location.longitude;
                    results.textContent = t(
                        "Вибрано: {place}. Збережіть налаштування, щоб застосувати координати.",
                        { place: button.textContent },
                    );
                    setSaveStatus(t("Є незбережені зміни"));
                    document.getElementById("latitude").focus();
                });
                results.append(button);
            }
        } catch (error) {
            results.textContent = t("{error} Координати можна ввести вручну.", {
                error: error.message,
            });
        } finally {
            setBusy(searchButton, false);
        }
    }

    form.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-step], button[data-interval]");
        if (!button) return;
        interval.value =
            button.dataset.interval ??
            Math.max(
                1,
                Math.min(86400, (numberOrNull(interval.value) ?? 60) + Number(button.dataset.step)),
            );
        updatePresets();
        setSaveStatus(t("Є незбережені зміни"));
    });
    form.addEventListener("input", () => {
        updatePresets();
        setSaveStatus(t("Є незбережені зміни"));
    });
    form.addEventListener("reset", (event) => {
        event.preventDefault();
        if (pending || savedConfiguration === null) return;
        populate(savedConfiguration);
        results.replaceChildren();
        searchInput.value = "";
        setSaveStatus(t("Зміни скасовано"));
    });
    searchButton.addEventListener("click", searchLocation);
    searchInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            searchLocation();
        }
    });
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (pending || !form.reportValidity()) return;
        let configuration;
        try {
            configuration = configurationFromForm(form);
        } catch (error) {
            setSaveStatus(error.message, "error");
            return;
        }
        pending = true;
        setBusy(saveButton, true);
        resetButton.disabled = true;
        form.querySelectorAll("fieldset").forEach((fieldset) => {
            fieldset.disabled = true;
        });
        setSaveStatus(t("Зберігаємо налаштування…"));
        try {
            await requestJSON("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(configuration),
            });
            savedConfiguration = configuration;
            setSaveStatus(t("Налаштування збережено"));
        } catch (error) {
            setSaveStatus(error.message, "error");
        } finally {
            pending = false;
            setBusy(saveButton, false);
            resetButton.disabled = false;
            form.querySelectorAll("fieldset").forEach((fieldset) => {
                fieldset.disabled = false;
            });
        }
    });
    loadConfiguration();
}
