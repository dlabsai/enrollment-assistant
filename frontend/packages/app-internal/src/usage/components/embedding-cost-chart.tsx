import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import type { JSX } from "react";
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
    type ChartConfig,
    ChartContainer,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import type { TimeRangeValue } from "../../lib/time-range";
import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    isHourlyTimeRange,
} from "../../lib/time-series";
import { formatUsageCost } from "../lib/formatters";
import type { UsageDaily } from "../types";

interface EmbeddingCostChartProps {
    data: UsageDaily[];
    timeRange: TimeRangeValue;
}

const chartConfig = {
    embeddingCost: {
        label: "Embedding cost",
        color: "var(--chart-5)",
    },
} satisfies ChartConfig;

export const EmbeddingCostChart = ({
    data,
    timeRange,
}: EmbeddingCostChartProps): JSX.Element => {
    const isHourly = isHourlyTimeRange(timeRange);

    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>Embedding cost over time</CardTitle>
                <CardDescription>
                    {isHourly
                        ? "Hourly embedding spend"
                        : "Daily embedding spend"}
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
                                id="fillEmbeddingCost"
                                x1="0"
                                x2="0"
                                y1="0"
                                y2="1"
                            >
                                <stop
                                    offset="5%"
                                    stopColor="var(--color-embeddingCost)"
                                    stopOpacity={0.8}
                                />
                                <stop
                                    offset="95%"
                                    stopColor="var(--color-embeddingCost)"
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
                            tickFormatter={(value: number) => formatUsageCost(value)}
                            tickLine={false}
                            width={64}
                        />
                        <ChartTooltip
                            content={
                                <ChartTooltipContent
                                    formatter={(value) =>
                                        typeof value === "number"
                                            ? formatUsageCost(value)
                                            : value
                                    }
                                    indicator="line"
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
                            dataKey="embeddingCost"
                            fill="url(#fillEmbeddingCost)"
                            stroke="var(--color-embeddingCost)"
                            type="natural"
                        />
                    </AreaChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
