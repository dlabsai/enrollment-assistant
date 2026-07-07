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
import type { PublicUsageDaily } from "../../usage/types";

interface PublicLeadsChartProps {
    data: PublicUsageDaily[];
    timeRange: TimeRangeValue;
}

const chartConfig = {
    leads: {
        label: "Leads",
        color: "var(--chart-4)",
    },
} satisfies ChartConfig;

export const PublicLeadsChart = ({
    data,
    timeRange,
}: PublicLeadsChartProps): JSX.Element => {
    const isHourly = isHourlyTimeRange(timeRange);

    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>Leads over time</CardTitle>
                <CardDescription>
                    {isHourly ? "Hourly leads" : "Daily leads"}
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
                                id="fillLeads"
                                x1="0"
                                x2="0"
                                y1="0"
                                y2="1"
                            >
                                <stop
                                    offset="5%"
                                    stopColor="var(--color-leads)"
                                    stopOpacity={0.6}
                                />
                                <stop
                                    offset="95%"
                                    stopColor="var(--color-leads)"
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
                            dataKey="leads"
                            fill="url(#fillLeads)"
                            stroke="var(--color-leads)"
                            type="natural"
                        />
                    </AreaChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
