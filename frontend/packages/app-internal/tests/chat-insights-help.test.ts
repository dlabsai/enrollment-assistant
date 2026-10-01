// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { test } from "vitest";

import { ChatInsightsHelp } from "../src/chat-insights/components/chat-insights-help";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("the help icon opens plain-language dashboard explanations", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);

    try {
        await act(() => root.render(createElement(ChatInsightsHelp)));
        const helpButton = host.querySelector<HTMLButtonElement>(
            'button[aria-label="About Chat Topics & Sources"]',
        );
        assert.ok(helpButton);

        await act(() => helpButton.click());

        const dialog = document.body.querySelector<HTMLElement>(
            '[role="dialog"]',
        );
        assert.ok(dialog);
        assert.match(
            dialog.textContent ?? "",
            /Understanding Chat Topics & Sources/u,
        );
        assert.match(
            dialog.textContent ?? "",
            /Current documents used/u,
        );
        assert.match(
            dialog.textContent ?? "",
            /not included in Current documents used or Current KB utilization/u,
        );
        assert.match(dialog.textContent ?? "", /Topic definitions/u);
        assert.match(
            dialog.textContent ?? "",
            /not audited facts or a measure of answer quality/u,
        );
    } finally {
        await act(() => root.unmount());
        host.remove();
    }
});
