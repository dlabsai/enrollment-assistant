import assert from "node:assert/strict";

import {
    createElement,
    isValidElement,
    type ComponentProps,
    type KeyboardEvent,
    type MouseEvent,
    type ReactNode,
} from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, test, vi } from "vitest";

import {
    ChatVolumeChart,
    TurnsVolumeChart,
} from "../src/chat-analytics/components/chat-volume-chart";

import { ChartInteractivePoint } from "../src/components/ui/chart";

const state = vi.hoisted(() => ({
    clickPlot: undefined as
        ((state: { activeLabel?: string }) => void) | undefined,
    targets: [] as ComponentProps<"circle">[],
}));

vi.mock("recharts", async (importOriginal) => {
    const actual = await importOriginal<typeof import("recharts")>();
    return {
        ...actual,
        ResponsiveContainer: ({ children }: { children: ReactNode }) =>
            children,
        LineChart: ({
            children,
            onClick,
        }: {
            children: ReactNode;
            onClick: typeof state.clickPlot;
        }) => {
            state.clickPlot = onClick;
            return createElement("svg", null, children);
        },
        CartesianGrid: () => null,
        XAxis: () => null,
        YAxis: () => null,
        Tooltip: () => null,
        Line: ({ dot }: { dot: ReactNode }) => {
            if (
                !isValidElement<ComponentProps<typeof ChartInteractivePoint>>(
                    dot,
                )
            )
                return null;
            return data.map((_, index) => {
                const target = ChartInteractivePoint({
                    ...dot.props,
                    index,
                    cx: 50 + index * 100,
                    cy: 100,
                });
                // The real chart's configured SVG target owns activation.
                assert.ok(target);
                state.targets.push(target.props);
                return createElement("g", { key: index }, target);
            });
        },
    };
});

const data = [
    {
        bucket_start: "2026-08-10T00:00:00Z",
        bucket_end: "2026-08-11T00:00:00Z",
        conversations: 2,
        turns: 3,
    },
    {
        bucket_start: "2026-08-11T00:00:00Z",
        bucket_end: "2026-08-12T00:00:00Z",
        conversations: 0,
        turns: 0,
    },
];

beforeEach(() => {
    state.clickPlot = undefined;
    state.targets = [];
});

for (const [name, Chart] of [
    ["Chats", ChatVolumeChart],
    ["Turns", TurnsVolumeChart],
] as const) {
    test(`${name} plot clicks and keyboard targets select the original bucket once`, () => {
        const onInspect = vi.fn();
        const props: ComponentProps<typeof Chart> = {
            canInspect: true,
            data,
            granularity: "day",
            onInspect,
        };
        const markup = renderToStaticMarkup(createElement(Chart, props));
        assert.match(markup, /role="button"/);
        assert.match(
            markup,
            new RegExp(`aria-label="Open ${name.toLowerCase()}:`),
        );
        assert.match(markup, /focus-visible:stroke-ring/);
        assert.ok(state.clickPlot);
        for (const [index, point] of data.entries()) {
            state.clickPlot({ activeLabel: point.bucket_start });
            assert.deepEqual(onInspect.mock.lastCall, [point]);
            for (const key of ["Enter", " "]) {
                const before = onInspect.mock.calls.length;
                const event = {
                    key,
                    preventDefault: vi.fn(),
                    stopPropagation: vi.fn(),
                };
                state.targets[index].onKeyDown?.(
                    event as unknown as KeyboardEvent<SVGCircleElement>,
                );
                assert.equal(onInspect.mock.calls.length, before + 1);
                assert.deepEqual(onInspect.mock.lastCall, [point]);
                assert.equal(event.preventDefault.mock.calls.length, 1);
            }
            const before = onInspect.mock.calls.length;
            const event = { stopPropagation: vi.fn() };
            state.targets[index].onClick?.(
                event as unknown as MouseEvent<SVGCircleElement>,
            );
            assert.equal(event.stopPropagation.mock.calls.length, 1);
            assert.equal(onInspect.mock.calls.length, before + 1);
            assert.deepEqual(onInspect.mock.lastCall, [point]);
        }
        const before = onInspect.mock.calls.length;
        state.clickPlot({});
        state.clickPlot({ activeLabel: "unknown-bucket" });
        state.targets[0].onKeyDown?.({
            key: "Escape",
        } as KeyboardEvent<SVGCircleElement>);
        assert.equal(onInspect.mock.calls.length, before);
    });

    test(`${name} has no drill-down targets without inspection rights or during refresh`, () => {
        const onInspect = vi.fn();
        const markup = renderToStaticMarkup(
            createElement(Chart, {
                canInspect: false,
                data,
                granularity: "day",
                onInspect,
            }),
        );
        state.clickPlot?.({ activeLabel: data[0].bucket_start });
        assert.equal(onInspect.mock.calls.length, 0);
        assert.equal(state.targets.length, 0);
        assert.doesNotMatch(markup, /role="button"/);
    });
}
