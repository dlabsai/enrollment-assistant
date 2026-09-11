import assert from "node:assert/strict";

import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { test, vi } from "vitest";

import { ChartContainer, ChartLegendContent } from "../src/components/ui/chart";

vi.mock("recharts", async (importOriginal) => {
    const actual = await importOriginal<typeof import("recharts")>();
    return {
        ...actual,
        ResponsiveContainer: ({ children }: { children: ReactNode }) =>
            children,
    };
});

test("selectable chart legends render keyboard-accessible toggle buttons", () => {
    const legend = createElement(ChartLegendContent, {
        hiddenKeys: new Set(["p95"]),
        onItemToggle: () => undefined,
        payload: [
            {
                color: "red",
                dataKey: "median",
                value: "median",
            },
            { color: "blue", dataKey: "p95", value: "p95" },
        ],
    });
    const markup = renderToStaticMarkup(
        createElement(ChartContainer, {
            children: legend,
            config: {
                median: { label: "Median", color: "red" },
                p95: { label: "P95", color: "blue" },
            },
        }),
    );

    assert.match(
        markup,
        /<button[^>]*aria-pressed="true"[^>]*>.*Median.*<\/button>/,
    );
    assert.match(
        markup,
        /<button[^>]*aria-pressed="false"[^>]*>.*P95.*<\/button>/,
    );
});
