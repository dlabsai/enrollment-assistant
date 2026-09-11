import assert from "node:assert/strict";

import {
    cloneElement,
    createElement,
    isValidElement,
    type ReactElement,
    type ReactNode,
} from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, test, vi } from "vitest";

import { ChatLengthChart } from "../src/chat-analytics/components/chat-length-chart";
import type { ChatAnalyticsBucket } from "../src/chat-analytics/types";
import { ResponseTimeDistributionChart } from "../src/quality/components/quality-charts";
import type { QualityResponseTimeBucket } from "../src/quality/types";

const chartState = vi.hoisted(() => ({
    tooltipProps: undefined as Record<string, unknown> | undefined,
}));

vi.mock("recharts", async (importOriginal) => {
    const actual = await importOriginal<typeof import("recharts")>();
    const React = await import("react");
    return {
        ...actual,
        Bar: (props: Record<string, unknown>) => {
            const shape = props.shape;
            return React.isValidElement(shape)
                ? React.cloneElement(
                      shape as ReactElement<Record<string, unknown>>,
                      {
                          fill: "var(--color-conversations)",
                          height: 12,
                          index: 0,
                          parentViewBox: {
                              height: 200,
                              width: 100,
                              x: 10,
                              y: 20,
                          },
                          width: 18,
                          x: 51,
                          y: 188,
                      },
                  )
                : null;
        },
        BarChart: ({ children }: { children: ReactNode }) =>
            React.createElement("div", null, children),
        CartesianGrid: () => null,
        ResponsiveContainer: ({ children }: { children: ReactNode }) =>
            children,
        usePlotArea: () => ({ x: 10, y: 20, width: 100, height: 200 }),
        Tooltip: (props: Record<string, unknown>) => {
            chartState.tooltipProps = props;
            return null;
        },
        XAxis: () => null,
        YAxis: () => null,
    };
});

const bucket: ChatAnalyticsBucket = {
    label: "3",
    conversations: 12,
    min_turns: 3,
    max_turns: 3,
    overflow: false,
};

const responseTimeBucket: QualityResponseTimeBucket = {
    label: "0-<5",
    lower_bound: 0,
    upper_bound: 5,
    count: 7,
    overflow: false,
};

beforeEach(() => {
    chartState.tooltipProps = undefined;
});

test("authorized Chat length categories render full-height keyboard actions", () => {
    const markup = renderToStaticMarkup(
        createElement(ChatLengthChart, {
            canInspect: true,
            data: [bucket],
            onInspect: () => undefined,
        }),
    );

    assert.match(markup, /aria-label="Open 12 chats with 3 turns"/u);
    assert.match(markup, /role="button"/u);
    assert.match(markup, /tabindex="0"/u);
    assert.match(markup, /height="12"/u);
    assert.match(markup, /height="200"/u);
});

test("response-time categories use the same full-height action target", () => {
    const markup = renderToStaticMarkup(
        createElement(ResponseTimeDistributionChart, {
            canInspect: true,
            data: [responseTimeBucket],
            onInspect: () => undefined,
        }),
    );

    assert.match(
        markup,
        /aria-label="Open 7 responses with response time 0–&lt;5s"/u,
    );
    assert.match(markup, /role="button"/u);
    assert.match(markup, /tabindex="0"/u);
    assert.match(markup, /height="12"/u);
    assert.match(markup, /height="200"/u);
});

test("unauthorized Chat length categories render without action semantics", () => {
    const markup = renderToStaticMarkup(
        createElement(ChatLengthChart, {
            canInspect: false,
            data: [bucket],
            onInspect: () => undefined,
        }),
    );

    assert.doesNotMatch(markup, /role="button"/u);
    assert.doesNotMatch(markup, /tabindex="0"/u);
});

test("Chat length hover guide is centered across the plot height", () => {
    renderToStaticMarkup(
        createElement(ChatLengthChart, {
            canInspect: false,
            data: [bucket],
            onInspect: () => undefined,
        }),
    );

    const cursor = chartState.tooltipProps?.cursor;
    assert.equal(isValidElement(cursor), true);
    const markup = renderToStaticMarkup(
        cloneElement(
            cursor as ReactElement<{
                height?: number;
                width?: number;
                x?: number;
                y?: number;
            }>,
            {
                height: 200,
                width: 30,
                x: 10,
                y: 20,
            },
        ),
    );
    assert.match(markup, /x1="25"/u);
    assert.match(markup, /x2="25"/u);
    assert.match(markup, /y1="20"/u);
    assert.match(markup, /y2="220"/u);
});
