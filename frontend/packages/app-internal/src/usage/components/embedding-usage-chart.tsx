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

interface EmbeddingUsageChartProps {
    data: UsageTimeSeriesPoint[];
    granularity: TimeGranularity;
}

const dataKeys = ["embeddingRequests", "embeddingTokens"] as const;

const chartConfig = {
    embeddingRequests: {
        label: "Embedding requests",
        color: "var(--chart-3)",
    },
    embeddingTokens: {
        label: "Embedding tokens",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

export const EmbeddingUsageChart = ({
    data,
    granularity,
}: EmbeddingUsageChartProps): JSX.Element => {
    const compactFormatter = useMemo(
        () => makeLocaleNumberFormatter({ notation: "compact" }),
        [],
    );
    const { hiddenSeries, toggleSeries, visibleSeries } =
        useVisibleChartSeries(dataKeys);
    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>Embedding usage over time</CardTitle>
                <CardDescription>
                    <span className="hidden @[540px]/card:block">
                        {timeGranularityLabel[granularity]} embedding requests
                        and token usage
                    </span>
                    <span className="@[540px]/card:hidden">
                        {timeGranularityLabel[granularity]} embedding usage
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
                            hide={!visibleSeries.has("embeddingRequests")}
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
                            hide={!visibleSeries.has("embeddingTokens")}
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
                            dataKey="embeddingRequests"
                            dot={false}
                            hide={!visibleSeries.has("embeddingRequests")}
                            isAnimationActive={false}
                            stroke="var(--color-embeddingRequests)"
                            strokeWidth={2}
                            type="linear"
                            yAxisId="requests"
                        />
                        <Line
                            connectNulls={false}
                            dataKey="embeddingTokens"
                            dot={false}
                            hide={!visibleSeries.has("embeddingTokens")}
                            isAnimationActive={false}
                            stroke="var(--color-embeddingTokens)"
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
