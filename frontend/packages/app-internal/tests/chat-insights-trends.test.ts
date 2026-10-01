// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, test } from "vitest";

import { TrendMatrix } from "../src/chat-insights/components/trend-matrix";
import type { TrendRow } from "../src/chat-insights/types";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

const rows: TrendRow[] = [
    {
        key: "billing",
        name: "Billing",
        points: [
            {
                bucket_start: "2026-08-10T00:00:00Z",
                bucket_end: "2026-08-11T00:00:00Z",
                chats: 1,
                answers: 0,
            },
            {
                bucket_start: "2026-08-11T00:00:00Z",
                bucket_end: "2026-08-12T00:00:00Z",
                chats: 2,
                answers: 1,
            },
        ],
    },
    {
        key: "aid",
        name: "Financial aid",
        points: [
            {
                bucket_start: "2026-08-10T00:00:00Z",
                bucket_end: "2026-08-11T00:00:00Z",
                chats: 3,
                answers: 0,
            },
            {
                bucket_start: "2026-08-11T00:00:00Z",
                bucket_end: "2026-08-12T00:00:00Z",
                chats: 0,
                answers: 0,
            },
        ],
    },
];

beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
});

afterEach(async () => {
    await act(() => root.unmount());
    container.remove();
});

const renderTrendMatrix = async (): Promise<void> => {
    await act(() =>
        root.render(
            createElement(TrendMatrix, {
                granularity: "day",
                topicRows: rows,
                sourceRows: [],
                documentRows: [],
            }),
        ),
    );
};

test("arrow keys move the trend grid focus and expose cell details", async () => {
    await renderTrendMatrix();

    const cells = [...container.querySelectorAll<HTMLElement>("[role='gridcell']")];
    assert.equal(cells.length, 4);
    assert.equal(cells.filter((cell) => cell.tabIndex === 0).length, 1);

    await act(() => cells[0]?.focus());
    await act(() =>
        cells[0]?.dispatchEvent(
            new KeyboardEvent("keydown", { bubbles: true, key: "ArrowRight" }),
        ),
    );

    assert.equal(document.activeElement, cells[1]);
    const tooltip = document.body.querySelector<HTMLElement>("[role='tooltip']");
    assert.ok(tooltip);
    assert.match(tooltip.textContent, /Billing/);
    assert.match(tooltip.textContent, /2 chats/);
    assert.match(tooltip.textContent, /1 answer using documents/);
});

test("pointer hover opens the trend tooltip and follows movement", async () => {
    await renderTrendMatrix();

    const cell = container.querySelector<HTMLElement>("[role='gridcell']");
    assert.ok(cell);
    await act(() =>
        cell.dispatchEvent(
            new PointerEvent("pointerover", {
                bubbles: true,
                clientX: 100,
                clientY: 100,
            }),
        ),
    );

    const tooltip = document.body.querySelector<HTMLElement>("[role='tooltip']");
    assert.ok(tooltip);
    assert.match(tooltip.textContent, /Billing/);
    const initialLeft = tooltip.style.left;

    await act(() =>
        cell.dispatchEvent(
            new PointerEvent("pointermove", {
                bubbles: true,
                clientX: 200,
                clientY: 100,
            }),
        ),
    );
    assert.notEqual(tooltip.style.left, initialLeft);

    await act(() =>
        cell.dispatchEvent(
            new PointerEvent("pointerout", {
                bubbles: true,
                relatedTarget: document.body,
            }),
        ),
    );
    assert.equal(document.body.querySelector("[role='tooltip']"), null);
});
