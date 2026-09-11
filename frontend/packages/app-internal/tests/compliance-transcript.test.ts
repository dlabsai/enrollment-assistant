// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { test, vi } from "vitest";

import { ConversationTranscript } from "../src/compliance/components/conversation-transcript";
import type { FlagDetail } from "../src/compliance/types";

const timestamp = "2026-09-01T12:00:00Z";
const evidence = String.raw`Admission is **guaranteed** for A &amp; B and \*all\* applicants.`;
const visibleEvidence = "Admission is guaranteed for A & B and *all* applicants.";
const sameRenderedText = String.raw`Admission is **guaranteed** for A & B and \*all\* applicants.`;
const highlightedText = (root: ParentNode): string =>
    [...root.querySelectorAll("mark[data-exact-highlight]")]
        .map((node) => node.textContent)
        .join("");
const transcript: FlagDetail["transcript"] = [
    {
        id: "root",
        parent_id: null,
        role: "user",
        content: "Can admission be promised?",
        created_at: timestamp,
    },
    {
        id: "target",
        parent_id: "root",
        role: "assistant",
        content: `# Program context\n\nEarlier guidance 😀.\n\n- ${evidence} admission is guaranteed. ${sameRenderedText}`,
        created_at: timestamp,
    },
    {
        id: "target-alternative",
        parent_id: "root",
        role: "assistant",
        content: "Admission is not guaranteed.",
        created_at: timestamp,
    },
    {
        id: "follow-up",
        parent_id: "target",
        role: "user",
        content: "First follow-up branch.",
        created_at: timestamp,
    },
    {
        id: "follow-up-alternative",
        parent_id: "target",
        role: "user",
        content: "Second follow-up branch.",
        created_at: timestamp,
    },
];

test("branch navigation keeps only exact formatted evidence highlighted and in view", async () => {
    const scrollIntoView = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
        await act(async () =>
            root.render(
                createElement(ConversationTranscript, {
                    evidence,
                    messages: transcript,
                    targetId: "target",
                }),
            ),
        );

        assert.equal(host.textContent?.split(visibleEvidence).length, 3);
        assert.match(host.textContent, /admission is guaranteed\./u);
        assert.doesNotMatch(host.textContent, /Admission is not guaranteed\./u);
        assert.match(host.textContent, /First follow-up branch\./u);
        const selected = host.querySelector('[aria-current="true"]');
        assert.ok(selected);
        assert.equal(highlightedText(selected), visibleEvidence);
        await act(
            async () =>
                new Promise<void>((resolve) => {
                    requestAnimationFrame(() => {
                        resolve();
                    });
                }),
        );
        assert.deepEqual(scrollIntoView.mock.lastCall, [
            { behavior: "smooth", block: "nearest", inline: "nearest" },
        ]);
        assert.strictEqual(
            scrollIntoView.mock.contexts.at(-1),
            selected.querySelector("mark[data-exact-highlight]"),
        );

        const nextBranch = host.querySelector<HTMLButtonElement>(
            'button[aria-label="Next branch"]',
        );
        assert.ok(nextBranch);
        await act(async () => nextBranch.click());

        assert.equal(highlightedText(host), visibleEvidence);
        assert.doesNotMatch(host.textContent, /Admission is not guaranteed\./u);
        assert.doesNotMatch(host.textContent, /First follow-up branch\./u);
        assert.match(host.textContent, /Second follow-up branch\./u);
    } finally {
        scrollIntoView.mockRestore();
        await act(async () => root.unmount());
        host.remove();
    }
});
