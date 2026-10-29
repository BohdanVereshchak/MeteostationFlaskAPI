import { t } from "./i18n.js";
import { METRICS, formatNumber, formatTimestamp, numberOrNull, parseTimestamp } from "./data.js";
import { appendCells } from "./ui.js";

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

function svgElement(name, attributes, text = "") {
    const element = document.createElementNS(SVG_NAMESPACE, name);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
    element.textContent = text;
    return element;
}

function chartSegments(points, metric, maximumGapMs) {
    const segments = [];
    let segment = [];
    for (const point of points) {
        const previous = segment.at(-1);
        const missing = numberOrNull(point[metric]) === null;
        const gap = previous && point.date - previous.date > maximumGapMs;
        if (missing || gap) {
            if (segment.length) segments.push(segment);
            segment = [];
        }
        if (!missing) segment.push(point);
    }
    if (segment.length) segments.push(segment);
    return segments;
}

export function createTimeChart(container) {
    let records = [];
    let metric = "temperature";
    let bucketSeconds = 360;
    let previousWidth = 0;
    let frame = 0;

    function render() {
        const width = Math.max(240, container.clientWidth);
        const height = container.classList.contains("time-chart-large") ? 260 : 168;
        const padding = { top: 18, right: 12, bottom: 25, left: 43 };
        const points = records
            .map((record) => ({ ...record, date: parseTimestamp(record.timestamp) }))
            .filter((record) => record.date)
            .sort((a, b) => a.date - b.date);
        const values = points
            .map((point) => numberOrNull(point[metric]))
            .filter((value) => value !== null);
        const definition = METRICS[metric];
        container.replaceChildren();
        if (!values.length) {
            const empty = document.createElement("p");
            empty.className = "chart-empty";
            empty.textContent = t("За цей період немає вимірювань");
            container.append(empty);
            return;
        }
        const minimum = Math.min(...values);
        const maximum = Math.max(...values);
        const margin = Math.max((maximum - minimum) * 0.18, metric === "eco2" ? 10 : 0.5);
        const lower = minimum - margin;
        const upper = maximum + margin;
        const start = points[0].date.getTime();
        const duration = Math.max(points.at(-1).date - start, bucketSeconds * 1000);
        const x = (point) =>
            padding.left +
            ((point.date - start) / duration) * (width - padding.left - padding.right);
        const y = (point) =>
            padding.top +
            ((upper - point[metric]) / (upper - lower)) * (height - padding.top - padding.bottom);
        const chart = svgElement("svg", {
            viewBox: `0 0 ${width} ${height}`,
            role: "group",
            "aria-label": t("{metric}, {unit}. Стрілки перемикають точки.", {
                metric: definition.label,
                unit: definition.unit,
            }),
        });
        const tooltip = document.createElement("div");
        tooltip.className = "chart-tooltip";
        tooltip.hidden = true;
        for (let index = 0; index < 3; index++) {
            const position = padding.top + (index / 2) * (height - padding.top - padding.bottom);
            const value = upper - (index / 2) * (upper - lower);
            chart.append(
                svgElement("line", {
                    x1: padding.left,
                    x2: width - padding.right,
                    y1: position,
                    y2: position,
                    class: "chart-grid-line",
                }),
            );
            chart.append(
                svgElement(
                    "text",
                    {
                        x: padding.left - 8,
                        y: position + 4,
                        "text-anchor": "end",
                        class: "chart-axis-label",
                    },
                    formatNumber(value, metric === "eco2" ? 0 : 1),
                ),
            );
        }
        const labelIndexes = [
            ...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]),
        ];
        for (const index of labelIndexes) {
            const point = points[index];
            const label =
                duration > 172800000
                    ? formatTimestamp(point.date, { hour: undefined, minute: undefined })
                    : formatTimestamp(point.date, { day: undefined, month: undefined });
            chart.append(
                svgElement(
                    "text",
                    {
                        x: x(point),
                        y: height - 3,
                        "text-anchor":
                            index === 0 ? "start" : index === points.length - 1 ? "end" : "middle",
                        class: "chart-axis-label",
                    },
                    label,
                ),
            );
        }
        const segments = chartSegments(points, metric, bucketSeconds * 2000);
        for (const segment of segments) {
            const line = segment
                .map((point, index) => `${index ? "L" : "M"} ${x(point)} ${y(point)}`)
                .join(" ");
            if (segment.length > 1) {
                chart.append(
                    svgElement("path", {
                        d: `${line} L ${x(segment.at(-1))} ${height - padding.bottom} L ${x(segment[0])} ${height - padding.bottom} Z`,
                        class: "chart-area",
                    }),
                );
                chart.append(svgElement("path", { d: line, class: "chart-line" }));
            } else {
                chart.append(
                    svgElement("circle", {
                        cx: x(segment[0]),
                        cy: y(segment[0]),
                        r: 3,
                        class: "chart-dot",
                    }),
                );
            }
        }
        const validPoints = points.filter((point) => numberOrNull(point[metric]) !== null);
        const marker = svgElement("circle", {
            cx: x(validPoints.at(-1)),
            cy: y(validPoints.at(-1)),
            r: 4,
            class: "chart-dot",
        });
        chart.append(marker);
        const targets = [];
        function inspect(point) {
            tooltip.textContent = `${formatTimestamp(point.date)} · ${formatNumber(point[metric], definition.digits)} ${definition.unit}`;
            tooltip.hidden = false;
            marker.setAttribute("cx", x(point));
            marker.setAttribute("cy", y(point));
        }
        validPoints.forEach((point, index) => {
            const previousX = index ? x(validPoints[index - 1]) : padding.left;
            const nextX =
                index < validPoints.length - 1 ? x(validPoints[index + 1]) : width - padding.right;
            const left = index ? (previousX + x(point)) / 2 : padding.left;
            const right =
                index < validPoints.length - 1 ? (nextX + x(point)) / 2 : width - padding.right;
            const target = svgElement("rect", {
                x: left,
                y: padding.top,
                width: Math.max(1, right - left),
                height: height - padding.top - padding.bottom,
                tabindex: index === 0 ? 0 : -1,
                role: "button",
                "aria-label": `${formatTimestamp(point.date)}: ${formatNumber(point[metric], definition.digits)} ${definition.unit}`,
                class: "chart-hit",
            });
            target.addEventListener("pointerenter", () => inspect(point));
            target.addEventListener("click", () => inspect(point));
            target.addEventListener("focus", () => inspect(point));
            target.addEventListener("blur", () => {
                tooltip.hidden = true;
            });
            target.addEventListener("keydown", (event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key))
                    return;
                event.preventDefault();
                if (event.key === "Escape") {
                    tooltip.hidden = true;
                    return;
                }
                let next =
                    event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? targets.length - 1
                          : index + (event.key === "ArrowRight" ? 1 : -1);
                next = Math.max(0, Math.min(targets.length - 1, next));
                targets.forEach((item, position) =>
                    item.setAttribute("tabindex", position === next ? 0 : -1),
                );
                targets[next].focus();
            });
            targets.push(target);
            chart.append(target);
        });
        chart.addEventListener("pointerleave", () => {
            tooltip.hidden = true;
        });
        const details = document.createElement("details");
        details.className = "chart-data";
        const summary = document.createElement("summary");
        summary.textContent = t("Значення графіка у таблиці");
        const scroll = document.createElement("div");
        scroll.className = "table-scroll";
        const table = document.createElement("table");
        const head = table.createTHead().insertRow();
        appendCells(head, [t("Час, Київ"), `${definition.label}, ${definition.unit}`], true);
        const body = table.createTBody();
        points.forEach((point) =>
            appendCells(body.insertRow(), [
                formatTimestamp(point.date),
                formatNumber(point[metric], definition.digits),
            ]),
        );
        scroll.append(table);
        details.append(summary, scroll);
        container.append(chart, tooltip, details);
    }

    const observer = new ResizeObserver((entries) => {
        const width = Math.round(entries[0].contentRect.width);
        if (width === previousWidth) return;
        previousWidth = width;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(render);
    });
    observer.observe(container);
    window.addEventListener("pageshow", (event) => {
        if (event.persisted) observer.observe(container);
    });
    window.addEventListener("pagehide", () => {
        observer.disconnect();
        cancelAnimationFrame(frame);
    });
    return {
        update(series, selectedMetric, resolution) {
            records = series;
            metric = selectedMetric;
            bucketSeconds = resolution || 360;
            render();
            if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
                container.querySelector("svg")?.animate([{ opacity: 0.35 }, { opacity: 1 }], {
                    duration: 220,
                    easing: "ease-out",
                });
            }
        },
    };
}
