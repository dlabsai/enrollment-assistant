import assert from "node:assert/strict";

import {
    type ComponentProps,
    createElement,
    isValidElement,
    type KeyboardEvent,
    type ReactNode,
    type SVGProps,
} from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, test, vi } from "vitest";

import { ChartInteractiveBar } from "../src/components/ui/chart";
import {
    FeedbackChart,
    GuardrailChart,
} from "../src/quality/components/quality-charts";
import { getQualityDrilldownRange } from "../src/quality/lib/drilldown";
import type { QualitySeriesPoint } from "../src/quality/types";

type ReviewChartProps = ComponentProps<typeof FeedbackChart> &
    ComponentProps<typeof GuardrailChart>;

const state = vi.hoisted(() => ({
    hidden: new Set<string>(),
    targets: [] as {
        click: () => void;
        press: (key: string) => void;
    }[],
}));

vi.mock("../src/lib/chart-series", () => ({
    useVisibleChartSeries: (keys: string[]) => ({
        hiddenSeries: state.hidden,
        visibleSeries: new Set(keys.filter((key) => !state.hidden.has(key))),
        toggleSeries: () => undefined,
    }),
}));

// Recharts supplies layout and bubbles bar clicks. Keep our actual category
// control and event handlers so tests exercise drill-down behavior, not props.
vi.mock("recharts", async (importOriginal) => {
    const actual = await importOriginal<typeof import("recharts")>();
    return {
        ...actual,
        ResponsiveContainer: ({ children }: { children: ReactNode }) =>
            children,
        BarChart: ({ children }: { children: ReactNode }) =>
            createElement("svg", null, children),
        CartesianGrid: () => null,
        XAxis: () => null,
        YAxis: () => null,
        Legend: () => null,
        Tooltip: () => null,
        usePlotArea: () => ({ x: 10, y: 20, width: 100, height: 200 }),
        Bar: ({
            hide,
            onClick,
            shape,
        }: {
            hide?: boolean;
            onClick?: (entry: { payload: QualitySeriesPoint }) => void;
            shape?: ReactNode;
        }) => {
            if (hide) return null;
            const barClick = () => onClick?.({ payload: point });
            if (
                !isValidElement<ComponentProps<typeof ChartInteractiveBar>>(
                    shape,
                )
            ) {
                state.targets.push({ click: barClick, press: () => undefined });
                return createElement("rect", { height: 12, width: 18 });
            }
            const rendered = ChartInteractiveBar({
                ...shape.props,
                height: 12,
                width: 18,
                index: 0,
                x: 51,
                y: 188,
            });
            const target: unknown = rendered?.props.children[1];
            assert.ok(isValidElement<SVGProps<SVGRectElement>>(target));
            state.targets.push({
                click: () => {
                    target.props.onClick?.(
                        {} as Parameters<
                            NonNullable<typeof target.props.onClick>
                        >[0],
                    );
                    barClick();
                },
                press: (key) =>
                    target.props.onKeyDown?.({
                        key,
                        preventDefault: () => undefined,
                    } as KeyboardEvent<SVGRectElement>),
            });
            return rendered;
        },
    };
});

const point: QualitySeriesPoint = {
    bucket_start: "2026-08-01T12:00:00.000Z",
    bucket_end: "2026-08-01T13:00:00.000Z",
    thumbs_up: 2,
    thumbs_down: 0,
    retry_attempts: 3,
    blocked_responses: 1,
};

beforeEach(() => {
    state.hidden = new Set();
    state.targets = [];
});

test("category clicks stay on the plotted day with axes and a legend", () => {
    const buckets = Array.from({ length: 10 }, (_, index) => ({
        bucket_start: new Date(Date.UTC(2026, 7, index + 1)).toISOString(),
        bucket_end: new Date(Date.UTC(2026, 7, index + 2)).toISOString(),
    }));
    const onInspect = vi.fn();
    const targets = buckets.map((bucket, index) => {
        // Plot: x=10, y=20, width=100, height=200. The enclosing chart also
        // contains axes/legend space that must never expand the click bands.
        const geometry = {
            index,
            x: 12 + index * 10,
            y: 188,
            width: 6,
            height: 12,
            parentViewBox: { x: 0, y: 0, width: 140, height: 280 },
        };
        const rendered = ChartInteractiveBar({
            ...geometry,
            canActivate: true,
            getActionLabel: () => `Open ${bucket.bucket_start}`,
            itemCount: buckets.length,
            onActivate: (selectedIndex) =>
                onInspect(
                    getQualityDrilldownRange(
                        { timeRange: "all" },
                        buckets[selectedIndex],
                    ),
                ),
        });
        const target: unknown = rendered?.props.children[1];
        assert.ok(isValidElement<SVGProps<SVGRectElement>>(target));
        assert.equal(target.props.y, 20);
        assert.equal(target.props.height, 200);
        return target.props;
    });

    for (const [index, bucket] of buckets.entries()) {
        // Click the bar centre and the space directly above that same bar.
        for (const y of [194, 50]) {
            const x = 15 + index * 10;
            const hits = targets.filter(
                (target) =>
                    x >= Number(target.x) &&
                    x < Number(target.x) + Number(target.width) &&
                    y >= Number(target.y) &&
                    y < Number(target.y) + Number(target.height),
            );
            assert.equal(hits.length, 1);
            const [hit] = hits;
            hit.onClick?.({} as Parameters<NonNullable<typeof hit.onClick>>[0]);
            assert.deepEqual(onInspect.mock.lastCall, [
                {
                    start: bucket.bucket_start,
                    endBefore: bucket.bucket_end,
                    timeRange: "custom",
                },
            ]);
        }
    }
});

const cases = [
    {
        chart: FeedbackChart,
        hidden: "thumbs_up",
        expected: "thumbs_down",
        label: "Thumbs down: 0",
    },
    {
        chart: FeedbackChart,
        hidden: "thumbs_down",
        expected: "thumbs_up",
        label: "Thumbs up: 2",
    },
    {
        chart: GuardrailChart,
        hidden: "retry_attempts",
        expected: "blocked",
        label: "Blocked responses: 1",
    },
    {
        chart: GuardrailChart,
        hidden: "blocked_responses",
        expected: "retried",
        label: "Retry attempts: 3",
    },
] as const;

for (const { chart, hidden, expected, label } of cases) {
    test(`isolated ${label} opens its exact bucket by category click or keyboard`, () => {
        state.hidden.add(hidden);
        const onInspect = vi.fn();
        const markup = renderToStaticMarkup(
            createElement<ReviewChartProps>(chart, {
                canInspect: true,
                data: [point],
                granularity: "hour",
                onInspect,
            }),
        );

        assert.match(markup, new RegExp(`aria-label="Open ${label}`));
        assert.match(markup, /role="button"/u);
        assert.match(markup, /tabindex="0"/u);
        assert.match(markup, /height="12"/u);
        assert.match(markup, /height="200"/u);
        assert.equal(state.targets.length, 1);
        const [target] = state.targets;
        target.click();
        assert.deepEqual(onInspect.mock.calls, [[point, expected]]);
        target.press("Enter");
        target.press(" ");
        target.press("Escape");
        assert.deepEqual(onInspect.mock.calls, [
            [point, expected],
            [point, expected],
            [point, expected],
        ]);
    });

    test(`isolated ${label} has no drill-down without inspection permission`, () => {
        state.hidden.add(hidden);
        const onInspect = vi.fn();
        const markup = renderToStaticMarkup(
            createElement<ReviewChartProps>(chart, {
                canInspect: false,
                data: [point],
                granularity: "hour",
                onInspect,
            }),
        );
        assert.doesNotMatch(markup, /role="button"|tabindex="0"/u);
        state.targets[0].click();
        state.targets[0].press("Enter");
        state.targets[0].press(" ");
        assert.equal(onInspect.mock.calls.length, 0);
    });
}

for (const { chart, expected } of [
    { chart: FeedbackChart, expected: ["thumbs_up", "thumbs_down"] },
    { chart: GuardrailChart, expected: ["retried", "blocked"] },
] as const) {
    test(`${chart.name} keeps distinct bar actions with both series visible`, () => {
        const onInspect = vi.fn();
        const markup = renderToStaticMarkup(
            createElement<ReviewChartProps>(chart, {
                canInspect: true,
                data: [point],
                granularity: "hour",
                onInspect,
            }),
        );
        assert.doesNotMatch(markup, /height="200"/u);
        assert.equal(state.targets.length, 2);
        for (const target of state.targets) target.click();
        assert.deepEqual(
            onInspect.mock.calls,
            expected.map((value) => [point, value]),
        );
    });
}
