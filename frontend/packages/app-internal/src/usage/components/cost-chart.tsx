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

interface CostChartProps {
    data: UsageDaily[];
    timeRange: TimeRangeValue;
}

const chartConfig = {
    cost: {
        label: "LLM cost",
        color: "var(--chart-4)",
    },
} satisfies ChartConfig;

export const CostChart = ({ data, timeRange }: CostChartProps): JSX.Element => {
    const isHourly = isHourlyTimeRange(timeRange);

    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>LLM cost over time</CardTitle>
                <CardDescription>
                    {isHourly ? "Hourly LLM spend" : "Daily LLM spend"}
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
                                id="fillCost"
                                x1="0"
                                x2="0"
                                y1="0"
                                y2="1"
                            >
                                <stop
                                    offset="5%"
                                    stopColor="var(--color-cost)"
                                    stopOpacity={0.9}
                                />
                                <stop
                                    offset="95%"
                                    stopColor="var(--color-cost)"
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
                            dataKey="cost"
                            fill="url(#fillCost)"
                            stroke="var(--color-cost)"
                            type="natural"
                        />
                    </AreaChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
