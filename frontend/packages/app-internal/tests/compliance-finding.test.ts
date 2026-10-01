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
vi.mock("../src/compliance/components/unsaved-changes", () => ({
    UnsavedChanges: () => null,
}));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
const typeComment = async (value: string): Promise<void> => {
    const input = host.querySelector("textarea");
    assert.ok(input);
    await act(async () => {
        Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype,
            "value",
        )?.set?.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
    });
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
        comment: "Verified by the policy owner.",
        reviewer: "Current lawyer",
        created_at: "2026-09-02T10:00:00Z",
        revision: 1,
    };
    api.post.mockResolvedValue(decision);
    await render();

    assert.match(host.textContent, new RegExp(finding.title, "u"));
    const title = host.querySelector('[data-slot="card-title"]');
    const categories = host.querySelector('[aria-label="Categories"]');
    assert.equal(title?.parentElement, categories?.parentElement);
    assert.equal(title?.parentElement?.getAttribute("data-slot"), "card-header");
    assert.match(host.textContent, /Misinformation/u);
    assert.match(host.textContent, /Regulatory Compliance/u);
    assert.match(host.textContent, new RegExp(finding.explanation, "u"));
    assert.doesNotMatch(host.textContent, /Decision history/u);
    assert.doesNotMatch(host.textContent, /Decision comment \(optional\)/u);
    assert.equal(
        host.querySelector("textarea")?.getAttribute("placeholder"),
        "Decision comment (optional)",
    );
    assert.equal(
        host.querySelector("textarea")?.getAttribute("aria-label"),
        "Decision comment (optional)",
    );
    await typeComment(decision.comment);
    await act(async () => button("Confirm").click());

    assert.deepEqual(api.post.mock.calls[0], [
        `/compliance/flags/${finding.id}/decision`,
        {
            state: "confirmed",
            comment: decision.comment,
            expected_revision: 0,
        },
    ]);
    assert.equal(onSaved.mock.calls.length, 1);
    assert.doesNotMatch(host.textContent, /Decision history/u);
    const history = host.querySelector('section[aria-label="Decision history"]');
    assert.ok(history);
    assert.match(history.textContent, /Confirmed/u);
    assert.match(history.textContent, /by Current lawyer/u);
    assert.doesNotMatch(
        host.querySelector('[data-slot="card-footer"]')?.textContent ?? "",
        /Current lawyer/u,
    );
    assert.match(host.textContent, new RegExp(decision.comment, "u"));
});

test("changing a decision reveals the comment editor", async () => {
    await render({
        ...finding,
        state: "confirmed",
        revision: 1,
        decisions: [
            {
                state: "confirmed",
                comment: null,
                reviewer: "Current lawyer",
                created_at: "2026-09-02T10:00:00Z",
                revision: 1,
            },
        ],
    });
    const content = host.querySelector<HTMLDivElement>(
        '[data-slot="card-content"]',
    );
    assert.ok(content);
    Object.defineProperty(content, "scrollHeight", {
        configurable: true,
        value: 640,
    });
    content.scrollTop = 20;

    await act(async () => button("Change decision").click());

    assert.equal(content.scrollTop, 640);
    assert.equal(
        host.querySelector("textarea")?.getAttribute("placeholder"),
        "Decision comment (optional)",
    );
});

test("a historical flag without categories is identified", async () => {
    await render({ ...finding, categories: null });

    assert.match(host.textContent, /Not categorized/u);
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
    assert.equal(button("Confirm").getAttribute("aria-busy"), "true");
    assert.equal(button("Dismiss").getAttribute("aria-busy"), "true");
    assert.equal(button("Confirm").textContent, "Confirm");
    assert.equal(button("Dismiss").textContent, "Dismiss");

    await act(async () =>
        finish?.({
            state: "confirmed",
            comment: null,
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
    await typeComment("Keep this comment.");
    await act(async () => button("Confirm").click());

    assert.equal(onReload.mock.calls.length, 1);
    assert.equal(host.querySelector("textarea")?.value, "Keep this comment.");
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
