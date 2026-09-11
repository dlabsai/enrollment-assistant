// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, test, vi } from "vitest";

import { FindingCard } from "../src/compliance/components/finding-card";
import type { Finding } from "../src/compliance/types";
import { finding } from "./compliance-fixtures";

const api = vi.hoisted(() => ({
    post: vi.fn<(endpoint: string, body: unknown) => Promise<unknown>>(),
}));
vi.mock("../src/auth/hooks/use-authenticated-api", () => ({
    useAuthenticatedApi: () => api,
}));

let host: HTMLDivElement;
let root: Root;
const onSaved = vi.fn();
const onReload = vi.fn();

const render = async (value: Finding = finding): Promise<void> => {
    await act(async () =>
        root.render(
            createElement(FindingCard, {
                finding: value,
                nextAction: null,
                onSaved,
                onReload,
                previousAction: null,
            }),
        ),
    );
};
const button = (label: string): HTMLButtonElement => {
    const result = [...host.querySelectorAll("button")].find(
        (node) => node.textContent === label,
    );
    assert.ok(result, `Missing action: ${label}`);
    return result;
};

beforeEach(() => {
    api.post.mockReset();
    onSaved.mockReset();
    onReload.mockReset();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
});

afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
});

test("a reviewer can decide a flag from its explanation", async () => {
    const decision = {
        state: "confirmed" as const,
        reviewer: "Current lawyer",
        created_at: "2026-09-02T10:00:00Z",
        revision: 1,
    };
    api.post.mockResolvedValue(decision);
    await render();

    assert.match(host.textContent, new RegExp(finding.explanation, "u"));
    await act(async () => button("Confirm").click());

    assert.deepEqual(api.post.mock.calls[0], [
        `/compliance/flags/${finding.id}/decision`,
        { state: "confirmed", expected_revision: 0 },
    ]);
    assert.equal(onSaved.mock.calls.length, 1);
    assert.match(host.textContent, /Confirmed by Current lawyer/u);
});

test("decision actions stay stable while a save is pending", async () => {
    let finish: ((value: unknown) => void) | undefined;
    api.post.mockReturnValue(
        new Promise((resolve) => {
            finish = resolve;
        }),
    );
    await render();
    await act(async () => {
        button("Confirm").click();
        await Promise.resolve();
    });

    assert.equal(button("Confirm").disabled, true);
    assert.equal(button("Dismiss").disabled, true);
    assert.equal(button("Confirm").textContent, "Confirm");
    assert.equal(button("Dismiss").textContent, "Dismiss");

    await act(async () =>
        finish?.({
            state: "confirmed",
            reviewer: "Current lawyer",
            created_at: "2026-09-02T10:00:00Z",
            revision: 1,
        }),
    );
});

test("a stale decision quietly reloads the latest revision", async () => {
    api.post.mockRejectedValue(
        Object.assign(new Error("412: Decision changed"), {
            status: 412,
            detail: "Decision changed",
        }),
    );
    await render();
    await act(async () => button("Confirm").click());

    assert.equal(onReload.mock.calls.length, 1);
    assert.doesNotMatch(host.textContent, /412:/u);
});

test("an evidence conflict remains visible until the reviewer reloads", async () => {
    const detail =
        "The original evidence can no longer be verified. Start a new screening.";
    api.post.mockRejectedValue(
        Object.assign(new Error(`409: ${detail}`), {
            status: 409,
            detail,
        }),
    );
    await render();
    await act(async () => button("Dismiss").click());

    assert.equal(onReload.mock.calls.length, 0);
    assert.match(host.textContent, new RegExp(detail, "u"));
    assert.doesNotMatch(host.textContent, /409:/u);
    await act(async () => button("Reload flag").click());
    assert.equal(onReload.mock.calls.length, 1);
    assert.doesNotMatch(host.textContent, new RegExp(detail, "u"));
});
