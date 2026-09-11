// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, test, vi } from "vitest";

import { ChatVolumeChart } from "../src/chat-analytics/components/chat-volume-chart";
import { formatLocaleNumber, formatUsdCost } from "../src/lib/number-format";
import { formatTimeSeriesTooltipLabel } from "../src/lib/time-series";
import { ResponsivenessChart } from "../src/quality/components/quality-charts";
import { CostChart } from "../src/usage/components/cost-chart";

// Only container measurement is supplied: real series, axes, tooltip state,
// legends and interactive dots are rendered by Recharts.
vi.mock("recharts", async (importOriginal) => {
    const actual = await importOriginal<typeof import("recharts")>();
    return {
        ...actual,
        ResponsiveContainer: (
            props: ComponentProps<typeof actual.ResponsiveContainer>,
        ) =>
            createElement(actual.ResponsiveContainer, {
                ...props,
                initialDimension: { width: 600, height: 280 },
            }),
    };
});

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let container: HTMLDivElement;
const time = "2026-08-10T00:00:00Z";
const bucket = { bucket_start: time, bucket_end: "2026-08-11T00:00:00Z" };

beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
        function (this: HTMLElement) {
            return new DOMRect(
                0,
                0,
                600,
                this.classList.contains("recharts-legend-wrapper") ? 20 : 280,
            );
        },
    );
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(600);
});
afterEach(async () => {
    await act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
});
const hover = async (): Promise<void> => {
    const chart = container.querySelector(".recharts-wrapper");
    assert.ok(chart);
    await act(async () => {
        chart.dispatchEvent(
            new MouseEvent("mousemove", {
                bubbles: true,
                clientX: 70,
                clientY: 100,
            }),
        );
        await new Promise((resolve) => requestAnimationFrame(resolve));
    });
};
const texts = (slot: string): string[] =>
    [...container.querySelectorAll(`[data-slot="chart-tooltip-${slot}"]`)].map(
        (node) => node.textContent ?? "",
    );
const clickLegend = async (label: string): Promise<void> => {
    const button = [...container.querySelectorAll("button")].find((node) =>
        node.textContent?.includes(label),
    );
    assert.ok(button, label);
    await act(() => button.click());
};

test("cost tooltip reads the plotted metric, category and tiny USD value", async () => {
    await act(() =>
        root.render(
            createElement(CostChart, {
                granularity: "day",
                data: [
                    {
                        ...bucket,
                        requests: 1,
                        tokens: 2,
                        cost: 0.00001,
                        embeddingRequests: 0,
                        embeddingTokens: 0,
                        embeddingCost: 0,
                        errors: 0,
                        avgDuration: 1,
                    },
                ],
            }),
        ),
    );
    await hover();
    assert.deepEqual(texts("heading"), [
        formatTimeSeriesTooltipLabel(time, "day"),
    ]);
    assert.deepEqual(texts("label"), ["LLM cost"]);
    assert.deepEqual(texts("value"), [formatUsdCost(0.00001)]);
    assert.equal(
        container.querySelectorAll('[data-slot="chart-tooltip-indicator"]')
            .length,
        1,
    );
});

test("response tooltip reflects actual series units and legend visibility", async () => {
    const samples = 1234;
    const props: ComponentProps<typeof ResponsivenessChart> = {
        canInspect: false,
        onInspect: vi.fn(),
        granularity: "day",
        data: [{ ...bucket, median_seconds: 12.5, p95_seconds: 40, samples }],
    };
    await act(() => root.render(createElement(ResponsivenessChart, props)));
    await hover();
    assert.deepEqual(texts("label"), ["Median", "P95"]);
    assert.deepEqual(texts("value"), [
        `${formatLocaleNumber(12.5)}s`,
        `${formatLocaleNumber(40)}s`,
    ]);
    assert.deepEqual(texts("footer"), [
        `${formatLocaleNumber(samples)} samples`,
    ]);
    await clickLegend("Median");
    assert.deepEqual(texts("label"), ["P95"]);
    assert.deepEqual(texts("value"), [`${formatLocaleNumber(40)}s`]);
    await clickLegend("P95");
    assert.deepEqual(texts("label"), ["P95"]);
    await clickLegend("Median");
    await clickLegend("P95");
    assert.deepEqual(texts("label"), ["Median"]);
    assert.deepEqual(texts("heading"), [
        formatTimeSeriesTooltipLabel(time, "day"),
    ]);
    assert.equal(
        container.querySelectorAll('[data-slot="chart-tooltip-indicator"]')
            .length,
        1,
    );
    await act(() =>
        root.render(
            createElement(ResponsivenessChart, {
                ...props,
                data: [{ ...props.data[0], median_seconds: 14 }],
            }),
        ),
    );
    await hover();
    assert.deepEqual(texts("label"), ["Median"]);
    assert.deepEqual(texts("value"), ["14s"]);
});

test("a singleton volume series stays visible with permission-aware activation", async () => {
    const onInspect = vi.fn();
    const point = { ...bucket, conversations: 2, turns: 3 };
    const props = {
        data: [point],
        granularity: "day" as const,
        canInspect: true,
        onInspect,
    };
    await act(() => root.render(createElement(ChatVolumeChart, props)));
    const button = container.querySelector('circle[role="button"]');
    assert.ok(button);
    const fill = button.getAttribute("fill");
    assert.ok(fill?.startsWith("var(--color-"));
    for (const key of ["Enter", " "]) {
        await act(() =>
            button.dispatchEvent(
                new KeyboardEvent("keydown", { key, bubbles: true }),
            ),
        );
    }
    await act(() =>
        button.dispatchEvent(new MouseEvent("click", { bubbles: true })),
    );
    assert.deepEqual(onInspect.mock.calls, [[point], [point], [point]]);
    await act(() =>
        root.render(
            createElement(ChatVolumeChart, { ...props, canInspect: false }),
        ),
    );
    assert.equal(container.querySelector('circle[role="button"]'), null);
    const marker = container.querySelector(`circle[fill="${fill}"]`);
    assert.ok(marker);
    await act(() =>
        marker.dispatchEvent(new MouseEvent("click", { bubbles: true })),
    );
    assert.equal(onInspect.mock.calls.length, 3);
});
