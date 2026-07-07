import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { type JSX, useMemo } from "react";
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
    type ChartConfig,
    ChartContainer,
    ChartLegend,
    ChartLegendContent,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { makeLocaleNumberFormatter } from "../../lib/number-format";
import type { TimeRangeValue } from "../../lib/time-range";
import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    isHourlyTimeRange,
} from "../../lib/time-series";
import type { UsageDaily } from "../types";

interface EmbeddingUsageChartProps {
    data: UsageDaily[];
    timeRange: TimeRangeValue;
}

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
    timeRange,
}: EmbeddingUsageChartProps): JSX.Element => {
    const compactFormatter = useMemo(
        () => makeLocaleNumberFormatter({ notation: "compact" }),
        [],
    );
    const isHourly = isHourlyTimeRange(timeRange);

    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>Embedding usage over time</CardTitle>
                <CardDescription>
                    <span className="hidden @[540px]/card:block">
                        {isHourly
                            ? "Hourly embedding requests and token usage"
                            : "Daily embedding requests and token usage"}
                    </span>
                    <span className="@[540px]/card:hidden">
                        {isHourly
                            ? "Hourly embedding usage"
                            : "Daily embedding usage"}
                    </span>
                </CardDescription>
            </CardHeader>
            <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
                <ChartContainer
                    className="aspect-auto h-[250px] w-full"
                    config={chartConfig}
                >
                    <AreaChart data={data}>
                        <defs>
                            <linearGradient
                                id="fillEmbeddingRequests"
                                x1="0"
                                x2="0"
                                y1="0"
                                y2="1"
                            >
                                <stop
                                    offset="5%"
                                    stopColor="var(--color-embeddingRequests)"
                                    stopOpacity={0.8}
                                />
                                <stop
                                    offset="95%"
                                    stopColor="var(--color-embeddingRequests)"
                                    stopOpacity={0.1}
                                />
                            </linearGradient>
                            <linearGradient
                                id="fillEmbeddingTokens"
                                x1="0"
                                x2="0"
                                y1="0"
                                y2="1"
                            >
                                <stop
                                    offset="5%"
                                    stopColor="var(--color-embeddingTokens)"
                                    stopOpacity={0.4}
                                />
                                <stop
                                    offset="95%"
                                    stopColor="var(--color-embeddingTokens)"
                                    stopOpacity={0.1}
                                />
                            </linearGradient>
                        </defs>
                        <CartesianGrid vertical={false} />
                        <XAxis
                            axisLine={false}
                            dataKey="date"
                            minTickGap={32}
                            tickFormatter={(value: string) =>
                                formatTimeSeriesTick(value, timeRange)
                            }
                            tickLine={false}
                            tickMargin={8}
                        />
                        <YAxis
                            axisLine={false}
                            tickFormatter={(value: number) =>
                                compactFormatter.format(value)
                            }
                            tickLine={false}
                            width={48}
                            yAxisId="requests"
                        />
                        <YAxis
                            axisLine={false}
                            orientation="right"
                            tickFormatter={(value: number) =>
                                compactFormatter.format(value)
                            }
                            tickLine={false}
                            width={56}
                            yAxisId="tokens"
                        />
                        <ChartTooltip
                            content={
                                <ChartTooltipContent
                                    indicator="dot"
                                    labelFormatter={(value) =>
                                        formatTimeSeriesTooltipLabel(
                                            typeof value === "string" ||
                                                typeof value === "number"
                                                ? String(value)
                                                : "",
                                            timeRange,
                                        )
                                    }
                                />
                            }
                            cursor={false}
                        />
                        <Area
                            dataKey="embeddingRequests"
                            fill="url(#fillEmbeddingRequests)"
                            stroke="var(--color-embeddingRequests)"
                            type="natural"
                            yAxisId="requests"
                        />
                        <Area
                            dataKey="embeddingTokens"
                            fill="url(#fillEmbeddingTokens)"
                            stroke="var(--color-embeddingTokens)"
                            type="natural"
                            yAxisId="tokens"
                        />
                        <ChartLegend
                            content={<ChartLegendContent />}
                            verticalAlign="bottom"
                        />
                    </AreaChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
