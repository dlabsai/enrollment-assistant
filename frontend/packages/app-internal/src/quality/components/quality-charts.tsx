import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import type { JSX, ReactNode } from "react";
import {
    Bar,
    BarChart,
    CartesianGrid,
    Line,
    LineChart,
    XAxis,
    YAxis,
} from "recharts";

import {
    ChartCategoryCursor,
    type ChartConfig,
    ChartContainer,
    ChartInteractiveBar,
    ChartLegend,
    ChartLegendContent,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { useVisibleChartSeries } from "../../lib/chart-series";
import { formatLocaleNumber } from "../../lib/number-format";
import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    type TimeGranularity,
} from "../../lib/time-series";
import type {
    QualityFeedbackRating,
    QualityGuardrailStatus,
    QualityResponseTimeBucket,
    QualityResponsivenessPoint,
    QualitySeriesPoint,
} from "../types";

interface TimeChartProps {
    granularity: TimeGranularity;
}

interface FeedbackChartProps extends TimeChartProps {
    canInspect: boolean;
    data: QualitySeriesPoint[];
    onInspect: (
        point: QualitySeriesPoint,
        rating: QualityFeedbackRating,
    ) => void;
}

interface GuardrailChartProps extends TimeChartProps {
    canInspect: boolean;
    data: QualitySeriesPoint[];
    onInspect: (
        point: QualitySeriesPoint,
        status: QualityGuardrailStatus,
    ) => void;
}

interface ResponsivenessChartProps extends TimeChartProps {
    canInspect: boolean;
    data: QualityResponsivenessPoint[];
    onInspect: (point: QualityResponsivenessPoint) => void;
}

interface ResponseTimeDistributionChartProps {
    canInspect: boolean;
    data: QualityResponseTimeBucket[];
    onInspect: (bucket: QualityResponseTimeBucket) => void;
}

interface ChartCardProps {
    children: ReactNode;
    description?: string;
    title: string;
}

type QualityChartDataKey =
    "thumbs_up" | "thumbs_down" | "retry_attempts" | "blocked_responses";
type ResponsivenessDataKey = "median_seconds" | "p95_seconds";

const feedbackDataKeys = ["thumbs_up", "thumbs_down"] as const;
const guardrailDataKeys = ["retry_attempts", "blocked_responses"] as const;
const responsivenessDataKeys = ["median_seconds", "p95_seconds"] as const;

interface BarChartCardProps extends TimeChartProps {
    canInspect: boolean;
    config: ChartConfig & Record<string, { label: string }>;
    data: QualitySeriesPoint[];
    dataKeys: readonly QualityChartDataKey[];
    onInspect: (
        point: QualitySeriesPoint,
        dataKey: QualityChartDataKey,
    ) => void;
    title: string;
}

const guardrailCountsConfig = {
    retry_attempts: {
        label: "Retry attempts",
        color: "var(--chart-1)",
    },
    blocked_responses: {
        label: "Blocked responses",
        color: "var(--destructive)",
    },
} satisfies ChartConfig;

const feedbackCountsConfig = {
    thumbs_up: {
        label: "Thumbs up",
        color: "var(--chart-2)",
    },
    thumbs_down: {
        label: "Thumbs down",
        color: "var(--destructive)",
    },
} satisfies ChartConfig;

const responsivenessConfig = {
    median_seconds: {
        label: "Median",
        color: "var(--chart-1)",
    },
    p95_seconds: {
        label: "P95",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

const responseDistributionConfig = {
    count: {
        label: "Responses",
        color: "var(--chart-4)",
    },
} satisfies ChartConfig;

const hasBucketStart = (value: unknown): value is { bucket_start: string } =>
    typeof value === "object" &&
    value !== null &&
    "bucket_start" in value &&
    typeof value.bucket_start === "string";

const formatSeconds = (value: number): string =>
    `${formatLocaleNumber(value, { maximumFractionDigits: 1 })}s`;

const formatResponseTimeBucket = (
    bucket: QualityResponseTimeBucket,
): string => {
    const lower = formatLocaleNumber(bucket.lower_bound, {
        maximumFractionDigits: 2,
    });
    if (bucket.upper_bound === null) {
        return `≥${lower}s`;
    }
    const upper = formatLocaleNumber(bucket.upper_bound, {
        maximumFractionDigits: 2,
    });
    return `${lower}–<${upper}s`;
};

const getResponseTimeBucketActionLabel = (
    bucket: QualityResponseTimeBucket,
): string =>
    `Open ${formatLocaleNumber(bucket.count)} ${bucket.count === 1 ? "response" : "responses"} with response time ${formatResponseTimeBucket(bucket)}`;

const formatSamples = (value: number): string =>
    `${formatLocaleNumber(value)} ${value === 1 ? "sample" : "samples"}`;

const ChartCard = ({
    children,
    description,
    title,
}: ChartCardProps): JSX.Element => (
    <Card>
        <CardHeader>
            <CardTitle>{title}</CardTitle>
            {description === undefined ? null : (
                <CardDescription>{description}</CardDescription>
            )}
        </CardHeader>
        <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
            {children}
        </CardContent>
    </Card>
);

const BarChartCard = ({
    canInspect,
    config,
    data,
    dataKeys,
    granularity,
    onInspect,
    title,
}: BarChartCardProps): JSX.Element => {
    const { hiddenSeries, toggleSeries, visibleSeries } =
        useVisibleChartSeries(dataKeys);
    const singleSeries = visibleSeries.size === 1;

    return (
        <ChartCard title={title}>
            <ChartContainer
                className="aspect-auto h-[280px] w-full"
                config={config}
            >
                <BarChart
                    accessibilityLayer
                    data={data}
                >
                    <CartesianGrid vertical={false} />
                    <XAxis
                        axisLine={false}
                        dataKey="bucket_start"
                        minTickGap={32}
                        tickFormatter={(value: string) =>
                            formatTimeSeriesTick(value, granularity)
                        }
                        tickLine={false}
                        tickMargin={8}
                    />
                    <YAxis
                        allowDecimals={false}
                        axisLine={false}
                        tickFormatter={(value: number) =>
                            formatLocaleNumber(value)
                        }
                        tickLine={false}
                        tickMargin={8}
                        width={48}
                    />
                    <ChartTooltip
                        content={
                            <ChartTooltipContent
                                indicator="dot"
                                labelFormatter={(value) =>
                                    formatTimeSeriesTooltipLabel(
                                        value,
                                        granularity,
                                    )
                                }
                            />
                        }
                        cursor={<ChartCategoryCursor />}
                        shared
                    />
                    {dataKeys.map((dataKey) => (
                        <Bar
                            cursor={canInspect ? "pointer" : "default"}
                            dataKey={dataKey}
                            fill={`var(--color-${dataKey})`}
                            hide={!visibleSeries.has(dataKey)}
                            isAnimationActive={false}
                            key={dataKey}
                            onClick={
                                canInspect && !singleSeries
                                    ? (entry): void => {
                                          const payload: unknown =
                                              entry.payload;
                                          if (!hasBucketStart(payload)) {
                                              return;
                                          }
                                          const point = data.find(
                                              (item) =>
                                                  item.bucket_start ===
                                                  payload.bucket_start,
                                          );
                                          if (point !== undefined) {
                                              onInspect(point, dataKey);
                                          }
                                      }
                                    : undefined
                            }
                            radius={4}
                            shape={
                                singleSeries ? (
                                    <ChartInteractiveBar
                                        canActivate={canInspect}
                                        getActionLabel={(index) => {
                                            const point = data[index];
                                            return point === undefined
                                                ? undefined
                                                : `Open ${config[dataKey].label}: ${formatLocaleNumber(point[dataKey])} · ${formatTimeSeriesTooltipLabel(point.bucket_start, granularity)}`;
                                        }}
                                        itemCount={data.length}
                                        onActivate={(index) => {
                                            const point = data[index];
                                            if (point !== undefined) {
                                                onInspect(point, dataKey);
                                            }
                                        }}
                                    />
                                ) : undefined
                            }
                        />
                    ))}
                    <ChartLegend
                        content={
                            <ChartLegendContent
                                hiddenKeys={hiddenSeries}
                                onItemToggle={toggleSeries}
                            />
                        }
                    />
                </BarChart>
            </ChartContainer>
        </ChartCard>
    );
};

export const ResponsivenessChart = ({
    canInspect,
    data,
    granularity,
    onInspect,
}: ResponsivenessChartProps): JSX.Element => {
    const { hiddenSeries, toggleSeries, visibleSeries } =
        useVisibleChartSeries<ResponsivenessDataKey>(responsivenessDataKeys);

    return (
        <ChartCard
            description="Backend processing time until the response is ready"
            title="Response time"
        >
            <ChartContainer
                className="aspect-auto h-[300px] w-full"
                config={responsivenessConfig}
            >
                <LineChart
                    accessibilityLayer
                    data={data}
                    onClick={
                        canInspect
                            ? (state): void => {
                                  const { activeLabel } = state;
                                  if (
                                      typeof activeLabel !== "string" &&
                                      typeof activeLabel !== "number"
                                  ) {
                                      return;
                                  }
                                  const point = data.find(
                                      (item) =>
                                          item.bucket_start ===
                                          String(activeLabel),
                                  );
                                  if (point !== undefined) {
                                      onInspect(point);
                                  }
                              }
                            : undefined
                    }
                    style={{ cursor: canInspect ? "pointer" : "default" }}
                >
                    <CartesianGrid vertical={false} />
                    <XAxis
                        axisLine={false}
                        dataKey="bucket_start"
                        minTickGap={32}
                        tickFormatter={(value: string) =>
                            formatTimeSeriesTick(value, granularity)
                        }
                        tickLine={false}
                        tickMargin={8}
                    />
                    <YAxis
                        axisLine={false}
                        tickFormatter={(value: number) => formatSeconds(value)}
                        tickLine={false}
                        tickMargin={8}
                        width={56}
                    />
                    <ChartTooltip
                        content={
                            <ChartTooltipContent
                                footerFormatter={(payload) => {
                                    const samples =
                                        payload[0]?.payload?.samples;
                                    return typeof samples === "number"
                                        ? formatSamples(samples)
                                        : undefined;
                                }}
                                indicator="line"
                                labelFormatter={(value) =>
                                    formatTimeSeriesTooltipLabel(
                                        value,
                                        granularity,
                                    )
                                }
                            />
                        }
                    />
                    <Line
                        connectNulls={false}
                        dataKey="median_seconds"
                        dot={false}
                        hide={!visibleSeries.has("median_seconds")}
                        isAnimationActive={false}
                        stroke="var(--color-median_seconds)"
                        strokeWidth={2}
                        type="linear"
                        unit="s"
                    />
                    <Line
                        connectNulls={false}
                        dataKey="p95_seconds"
                        dot={false}
                        hide={!visibleSeries.has("p95_seconds")}
                        isAnimationActive={false}
                        stroke="var(--color-p95_seconds)"
                        strokeWidth={2}
                        type="linear"
                        unit="s"
                    />
                    <ChartLegend
                        content={
                            <ChartLegendContent
                                hiddenKeys={hiddenSeries}
                                onItemToggle={toggleSeries}
                            />
                        }
                    />
                </LineChart>
            </ChartContainer>
        </ChartCard>
    );
};

export const ResponseTimeDistributionChart = ({
    canInspect,
    data,
    onInspect,
}: ResponseTimeDistributionChartProps): JSX.Element => {
    const chartData = data.map((bucket) => ({
        ...bucket,
        displayLabel: formatResponseTimeBucket(bucket),
    }));

    return (
        <ChartCard
            description="Responses grouped by backend processing time"
            title="Response time distribution"
        >
            <ChartContainer
                className="aspect-auto h-[280px] w-full"
                config={responseDistributionConfig}
            >
                <BarChart
                    accessibilityLayer
                    data={chartData}
                >
                    <CartesianGrid vertical={false} />
                    <XAxis
                        axisLine={false}
                        dataKey="displayLabel"
                        minTickGap={16}
                        tickLine={false}
                        tickMargin={8}
                    />
                    <YAxis
                        allowDecimals={false}
                        axisLine={false}
                        tickFormatter={(value: number) =>
                            formatLocaleNumber(value)
                        }
                        tickLine={false}
                        tickMargin={8}
                        width={48}
                    />
                    <ChartTooltip
                        content={<ChartTooltipContent />}
                        cursor={<ChartCategoryCursor />}
                        shared
                    />
                    <Bar
                        dataKey="count"
                        fill="var(--color-count)"
                        isAnimationActive={false}
                        shape={
                            <ChartInteractiveBar
                                canActivate={canInspect}
                                getActionLabel={(index) => {
                                    const bucket = data[index];
                                    return bucket === undefined
                                        ? undefined
                                        : getResponseTimeBucketActionLabel(
                                              bucket,
                                          );
                                }}
                                itemCount={data.length}
                                onActivate={(index) => {
                                    const bucket = data[index];
                                    if (bucket !== undefined) {
                                        onInspect(bucket);
                                    }
                                }}
                            />
                        }
                    />
                </BarChart>
            </ChartContainer>
        </ChartCard>
    );
};

export const FeedbackChart = ({
    canInspect,
    data,
    granularity,
    onInspect,
}: FeedbackChartProps): JSX.Element => (
    <BarChartCard
        canInspect={canInspect}
        config={feedbackCountsConfig}
        data={data}
        dataKeys={feedbackDataKeys}
        granularity={granularity}
        onInspect={(point, dataKey) => {
            onInspect(
                point,
                dataKey === "thumbs_down" ? "thumbs_down" : "thumbs_up",
            );
        }}
        title="Thumbs up and down"
    />
);

export const GuardrailChart = ({
    canInspect,
    data,
    granularity,
    onInspect,
}: GuardrailChartProps): JSX.Element => (
    <BarChartCard
        canInspect={canInspect}
        config={guardrailCountsConfig}
        data={data}
        dataKeys={guardrailDataKeys}
        granularity={granularity}
        onInspect={(point, dataKey) => {
            onInspect(
                point,
                dataKey === "blocked_responses" ? "blocked" : "retried",
            );
        }}
        title="Retries and blocked responses"
    />
);
