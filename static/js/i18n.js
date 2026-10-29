export function createTranslator(messages = {}) {
    return (message, values = {}) => {
        const translated = messages[message] ?? message;
        return translated.replace(/\{(\w+)\}/g, (placeholder, name) =>
            Object.hasOwn(values, name) ? String(values[name]) : placeholder,
        );
    };
}

const page = typeof document === "undefined" ? null : document;
const messages = page?.getElementById("translation-messages")?.textContent;

export const t = createTranslator(messages ? JSON.parse(messages) : {});
export const language = page?.documentElement.lang || "uk";
export const locale = language === "en" ? "en-GB" : "uk-UA";
