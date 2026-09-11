// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { ConfirmDialog } from "@va/shared/components/dialog";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { test, vi } from "vitest";

test("an asynchronous confirmation cannot be submitted or dismissed twice", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    let complete: (() => void) | undefined;
    const onConfirm = vi.fn(
        async () =>
            new Promise<void>((resolve) => {
                complete = resolve;
            }),
    );
    const onOpenChange = vi.fn();
    try {
        await act(async () =>
            root.render(
                createElement(ConfirmDialog, {
                    confirmLabel: "Restore as new version",
                    onConfirm,
                    onOpenChange,
                    open: true,
                    title: "Restore instructions?",
                }),
            ),
        );

        const actions = [...document.querySelectorAll("button")];
        const confirm = actions.find((action) =>
            action.textContent?.includes("Restore as new version"),
        );
        const cancel = actions.find(
            (action) => action.textContent?.trim() === "Cancel",
        );
        assert.ok(confirm);
        assert.ok(cancel);

        await act(async () => {
            confirm.click();
            confirm.click();
        });
        assert.equal(onConfirm.mock.calls.length, 1);
        assert.equal(confirm.disabled, true);
        assert.equal(cancel.disabled, true);
        assert.equal(confirm.getAttribute("aria-busy"), "true");
        assert.equal(onOpenChange.mock.calls.length, 0);

        await act(async () =>
            document.dispatchEvent(
                new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
            ),
        );
        assert.equal(onOpenChange.mock.calls.length, 0);

        await act(async () => complete?.());
        assert.deepEqual(onOpenChange.mock.calls, [[false]]);
    } finally {
        await act(async () => root.unmount());
        host.remove();
    }
});
