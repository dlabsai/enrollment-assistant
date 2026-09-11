import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { type JSX, useMemo } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
    type ChartConfig,
    ChartContainer,
    ChartLegend,
    ChartLegendContent,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { useVisibleChartSeries } from "../../lib/chart-series";
import { makeLocaleNumberFormatter } from "../../lib/number-format";
import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    type TimeGranularity,
    timeGranularityLabel,
} from "../../lib/time-series";
import type { UsageTimeSeriesPoint } from "../types";

interface UsageChartProps {
    data: UsageTimeSeriesPoint[];
    granularity: TimeGranularity;
}

const dataKeys = ["requests", "tokens"] as const;

const chartConfig = {
    requests: {
        label: "LLM requests",
        color: "var(--chart-1)",
    },
    tokens: {
        label: "LLM tokens",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

export const UsageChart = ({
    data,
    granularity,
}: UsageChartProps): JSX.Element => {
    const compactFormatter = useMemo(
        () => makeLocaleNumberFormatter({ notation: "compact" }),
        [],
    );
    const { hiddenSeries, toggleSeries, visibleSeries } =
        useVisibleChartSeries(dataKeys);
    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>LLM usage over time</CardTitle>
                <CardDescription>
                    <span className="hidden @[540px]/card:block">
                        {timeGranularityLabel[granularity]} LLM requests and
                        token usage
                    </span>
                    <span className="@[540px]/card:hidden">
                        {timeGranularityLabel[granularity]} LLM usage
                    </span>
                </CardDescription>
            </CardHeader>
            <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
                <ChartContainer
                    className="aspect-auto h-[250px] w-full"
                    config={chartConfig}
                >
                    <LineChart
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
                            hide={!visibleSeries.has("requests")}
                            tickFormatter={(value: number) =>
                                compactFormatter.format(value)
                            }
                            tickLine={false}
                            tickMargin={8}
                            width={48}
                            yAxisId="requests"
                        />
                        <YAxis
                            allowDecimals={false}
                            axisLine={false}
                            hide={!visibleSeries.has("tokens")}
                            orientation="right"
                            tickFormatter={(value: number) =>
                                compactFormatter.format(value)
                            }
                            tickLine={false}
                            tickMargin={8}
                            width={56}
                            yAxisId="tokens"
                        />
                        <ChartTooltip
                            content={
                                <ChartTooltipContent
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
                            dataKey="requests"
                            dot={false}
                            hide={!visibleSeries.has("requests")}
                            isAnimationActive={false}
                            stroke="var(--color-requests)"
                            strokeWidth={2}
                            type="linear"
                            yAxisId="requests"
                        />
                        <Line
                            connectNulls={false}
                            dataKey="tokens"
                            dot={false}
                            hide={!visibleSeries.has("tokens")}
                            isAnimationActive={false}
                            stroke="var(--color-tokens)"
                            strokeWidth={2}
                            type="linear"
                            yAxisId="tokens"
                        />
                        <ChartLegend
                            content={
                                <ChartLegendContent
                                    hiddenKeys={hiddenSeries}
                                    onItemToggle={toggleSeries}
                                />
                            }
                            verticalAlign="bottom"
                        />
                    </LineChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
