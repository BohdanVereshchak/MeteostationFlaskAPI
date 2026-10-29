import { t } from "./i18n.js";
export function setText(id, value) {
    document.getElementById(id).textContent = value;
}

export function showNotice(message = "") {
    const notice = document.getElementById("page-message");
    notice.textContent = message;
    notice.hidden = !message;
}

export function setConnection(id, { state, label }) {
    const element = document.getElementById(id);
    element.dataset.state = state;
    element.textContent = label;
}

export function markSelection(container, selected) {
    container.querySelectorAll("button").forEach((button) => {
        button.setAttribute("aria-pressed", String(button === selected));
    });
}

export function setBusy(button, busy) {
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
}

export function appendCells(row, values, header = false) {
    for (const value of values) {
        const cell = document.createElement(header ? "th" : "td");
        if (header) cell.scope = "col";
        cell.textContent = value;
        row.append(cell);
    }
}

export async function requestJSON(url, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
        const headers = new Headers(options.headers);
        if (
            url.startsWith("/") &&
            !["GET", "HEAD"].includes((options.method || "GET").toUpperCase())
        ) {
            headers.set("X-CSRF-Token", document.querySelector('meta[name="csrf-token"]').content);
        }
        const response = await fetch(url, { ...options, headers, signal: controller.signal });
        const data = await response.json();
        if (!response.ok) {
            const message = typeof data.error === "string" ? data.error : data.reason;
            const error = new Error(message || t("Не вдалося завантажити дані. Спробуйте ще раз."));
            error.status = response.status;
            throw error;
        }
        return data;
    } catch (error) {
        if (error.name === "AbortError")
            throw new Error(t("Сервер не відповів вчасно. Повторіть запит."));
        if (error instanceof TypeError)
            throw new Error(t("Немає зв’язку із сервером. Перевірте підключення."));
        if (error instanceof SyntaxError)
            throw new Error(t("Сервер повернув неочікувану відповідь. Повторіть запит пізніше."));
        throw error;
    } finally {
        clearTimeout(timeout);
    }
}

export function startAutoRefresh(refresh, intervalMs) {
    let busy = false;
    let timer = null;
    async function update() {
        if (document.hidden || busy) return;
        busy = true;
        try {
            await refresh();
        } finally {
            busy = false;
        }
    }
    function start() {
        if (timer === null) timer = setInterval(update, intervalMs);
    }
    start();
    document.addEventListener("visibilitychange", update);
    window.addEventListener("pagehide", () => {
        clearInterval(timer);
        timer = null;
    });
    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            start();
            update();
        }
    });
}
