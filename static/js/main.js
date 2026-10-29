if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.getElementById("main").animate(
        [
            { opacity: 0, transform: "translateY(6px)" },
            { opacity: 1, transform: "translateY(0)" },
        ],
        { duration: 260, easing: "ease-out" },
    );
}

document.getElementById("selected-station")?.addEventListener("change", () => {
    document.getElementById("station-switch").requestSubmit();
});

const menu = document.querySelector(".account-menu");
document.addEventListener("click", (event) => {
    if (menu?.open && !menu.contains(event.target)) menu.open = false;
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu?.open) {
        menu.open = false;
        menu.querySelector("summary").focus();
    }
});

const pageModules = {
    overview: () => import("./overview.js"),
    history: () => import("./history.js"),
    comparison: () => import("./comparison.js"),
    settings: () => import("./settings.js"),
};

const loadPage = pageModules[document.body.dataset.page];
if (loadPage) {
    loadPage()
        .then((module) => module.initialize())
        .catch(() => {
            const notice = document.getElementById("page-message");
            notice.textContent = "Не вдалося відкрити інтерфейс. Оновіть сторінку.";
            notice.hidden = false;
        });
}
