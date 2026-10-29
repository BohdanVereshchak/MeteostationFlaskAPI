import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createTranslator } from "../static/js/i18n.js";

const english = JSON.parse(
    readFileSync(new URL("../translations/en.json", import.meta.url), "utf8"),
);

test("the English catalog translates UI text and interpolates zero values", () => {
    const translate = createTranslator(english);
    assert.equal(translate("Температура"), "Temperature");
    assert.equal(translate("гПа"), "hPa");
    assert.equal(
        translate("{shown} із {total} записів", { shown: 0, total: 100 }),
        "0 of 100 readings",
    );
});

test("the source-language fallback and unknown messages stay intact", () => {
    assert.equal(createTranslator()("Огляд"), "Огляд");
    assert.equal(createTranslator(english)("A new message"), "A new message");
});

test("interpolation does not interpret values as messages or HTML", () => {
    const translate = createTranslator({ "{value} / {other}": "{value} / {other}" });
    assert.equal(
        translate("{value} / {other}", { value: "<b>{other}</b>", other: "plain" }),
        "<b>{other}</b> / plain",
    );
    assert.equal(translate("{value} / {other}"), "{value} / {other}");
});
