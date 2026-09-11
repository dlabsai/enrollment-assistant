import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import type { JSX } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
    type ChartConfig,
    ChartContainer,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { formatUsdCost } from "../../lib/number-format";
import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    type TimeGranularity,
    timeGranularityLabel,
} from "../../lib/time-series";
import type { UsageTimeSeriesPoint } from "../types";

interface CostChartProps {
    data: UsageTimeSeriesPoint[];
    granularity: TimeGranularity;
}

const chartConfig = {
    cost: {
        label: "LLM cost",
        color: "var(--chart-4)",
    },
} satisfies ChartConfig;

export const CostChart = ({
    data,
    granularity,
}: CostChartProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardTitle>LLM cost over time</CardTitle>
            <CardDescription>
                {timeGranularityLabel[granularity]} LLM spend
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
                        axisLine={false}
                        tickFormatter={(value: number) => formatUsdCost(value)}
                        tickLine={false}
                        tickMargin={8}
                        width={64}
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
                                valueFormatter={(value) =>
                                    typeof value === "number"
                                        ? formatUsdCost(value)
                                        : value
                                }
                            />
                        }
                    />
                    <Line
                        connectNulls={false}
                        dataKey="cost"
                        dot={false}
                        isAnimationActive={false}
                        stroke="var(--color-cost)"
                        strokeWidth={2}
                        type="linear"
                    />
                </LineChart>
            </ChartContainer>
        </CardContent>
    </Card>
);
