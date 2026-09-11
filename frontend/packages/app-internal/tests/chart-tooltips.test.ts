import assert from "node:assert/strict";

import { createElement, type ComponentProps, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { test, vi } from "vitest";

import {
    ChartContainer,
    ChartTooltipContent,
} from "../src/components/ui/chart";
import { formatLocaleNumber } from "../src/lib/number-format";

type TooltipProps = ComponentProps<typeof ChartTooltipContent>;

// Renderer unit tests supply payloads directly. Actual chart wiring is exercised
// by chart-rendering.test.ts using real Recharts and DOM events.
vi.mock("recharts", async (importOriginal) => ({
    ...(await importOriginal<typeof import("recharts")>()),
    ResponsiveContainer: ({ children }: { children: ReactNode }) => children,
}));

const textInSlot = (markup: string, slot: string): string[] =>
    [
        ...markup.matchAll(
            new RegExp(
                `data-slot="chart-tooltip-${slot}"[^>]*>(.*?)</(?:div|span)>`,
                "gs",
            ),
        ),
    ].map((match) => match[1].replace(/<[^>]*>/g, ""));

const renderTooltip = (props: TooltipProps): string =>
    renderToStaticMarkup(
        createElement(ChartContainer, {
            config: {
                count: { label: "Responses", color: "var(--chart-1)" },
                median: { label: "Median" },
                p95: { label: "P95" },
            },
            children: createElement(ChartTooltipContent, {
                active: true,
                ...props,
            }),
        }),
    );

test("single- and multi-row tooltips keep headings above localized metric rows", () => {
    const payload = [
        { dataKey: "median", value: 12.5, unit: "s", color: "var(--chart-1)" },
        { dataKey: "p95", value: 40, unit: "s", color: "var(--chart-2)" },
    ];
    for (const items of [payload, payload.slice(0, 1), payload.slice(1)]) {
        const markup = renderTooltip({
            indicator: "line",
            label: "Aug 10, 2026",
            payload: items,
        });
        assert.deepEqual(textInSlot(markup, "heading"), ["Aug 10, 2026"]);
        assert.ok(
            markup.indexOf('data-slot="chart-tooltip-heading"') <
                markup.indexOf('data-slot="chart-tooltip-row"'),
        );
        assert.deepEqual(
            textInSlot(markup, "label"),
            items.map((item) => (item.dataKey === "median" ? "Median" : "P95")),
        );
        assert.deepEqual(
            textInSlot(markup, "value"),
            items.map((item) => `${formatLocaleNumber(item.value)}s`),
        );
        assert.equal(
            (markup.match(/data-slot="chart-tooltip-indicator"/g) ?? []).length,
            items.length,
        );
    }
});

test("zero categories and values retain metric rows and value-only formatting", () => {
    const zero = renderTooltip({
        label: 0,
        payload: [{ dataKey: "count", value: 0 }],
    });
    assert.deepEqual(textInSlot(zero, "heading"), ["0"]);
    assert.deepEqual(textInSlot(zero, "label"), ["Responses"]);
    assert.deepEqual(textInSlot(zero, "value"), [formatLocaleNumber(0)]);
    const custom = renderTooltip({
        label: "Category",
        payload: [{ dataKey: "count", value: "unknown" }],
        valueFormatter: (value) => `Value: ${value}`,
    });
    assert.deepEqual(textInSlot(custom, "heading"), ["Category"]);
    assert.deepEqual(textInSlot(custom, "label"), ["Responses"]);
    assert.deepEqual(textInSlot(custom, "value"), ["Value: unknown"]);
});

test("missing and suppressed values neither create tooltips nor leak into footer context", () => {
    const suppressed = [
        { dataKey: "p95", value: 90, type: "none" },
        { dataKey: "median", value: null },
        { dataKey: "count" },
    ];
    for (const props of [
        { payload: [] },
        { payload: suppressed },
        { active: false, payload: [{ dataKey: "count", value: 1 }] },
    ]) {
        assert.equal(
            renderTooltip(props).includes('data-slot="chart-tooltip"'),
            false,
        );
    }
    const seen = vi.fn(
        (payload: NonNullable<TooltipProps["payload"]>) =>
            `${payload.length} visible metric`,
    );
    const markup = renderTooltip({
        label: "Category",
        payload: [...suppressed, { dataKey: "count", value: 1 }],
        footerFormatter: seen,
    });
    assert.deepEqual(textInSlot(markup, "label"), ["Responses"]);
    assert.deepEqual(textInSlot(markup, "footer"), ["1 visible metric"]);
    assert.equal(seen.mock.calls[0][0].length, 1);
    assert.ok(
        markup.indexOf('data-slot="chart-tooltip-footer"') >
            markup.indexOf('data-slot="chart-tooltip-value"'),
    );
});
