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

import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    type TimeGranularity,
} from "../../lib/time-series";
import type { AdoptionTimeSeriesPoint } from "../types";

interface AdoptionChartProps {
    data: AdoptionTimeSeriesPoint[];
    granularity: TimeGranularity;
    metric: "active_users" | "monthly_active_users";
    title: string;
    description: string;
}

const chartConfig = {
    active_users: {
        label: "Active users",
        color: "var(--chart-1)",
    },
    monthly_active_users: {
        label: "Monthly active users",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

export const AdoptionChart = ({
    data,
    metric,
    title,
    description,
    granularity,
}: AdoptionChartProps): JSX.Element => {
    const gradientId =
        metric === "active_users"
            ? "fillAdoptionActive"
            : "fillAdoptionMonthly";
    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>{title}</CardTitle>
                <CardDescription>{description}</CardDescription>
            </CardHeader>
            <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
                <ChartContainer
                    className="aspect-auto h-[280px] w-full"
                    config={chartConfig}
                >
                    <AreaChart data={data}>
                        <defs>
                            <linearGradient
                                id={gradientId}
                                x1="0"
                                x2="0"
                                y1="0"
                                y2="1"
                            >
                                <stop
                                    offset="5%"
                                    stopColor={`var(--color-${metric})`}
                                    stopOpacity={1}
                                />
                                <stop
                                    offset="95%"
                                    stopColor={`var(--color-${metric})`}
                                    stopOpacity={0.1}
                                />
                            </linearGradient>
                        </defs>
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
                            tickLine={false}
                            tickMargin={8}
                            width={48}
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
                        <Area
                            dataKey={metric}
                            fill={`url(#${gradientId})`}
                            isAnimationActive={false}
                            stroke={`var(--color-${metric})`}
                        />
                    </AreaChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
