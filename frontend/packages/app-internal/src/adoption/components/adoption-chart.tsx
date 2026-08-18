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

import type { AdoptionDaily } from "../types";

interface AdoptionChartProps {
    data: AdoptionDaily[];
    metric: "daily_active_users" | "monthly_active_users";
    title: string;
    description: string;
}

const tickFormatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
});
const tooltipFormatter = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
});

const parseAdoptionDate = (value: string): Date =>
    new Date(`${value}T00:00:00`);

const chartConfig = {
    daily_active_users: {
        label: "Daily active users",
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
}: AdoptionChartProps): JSX.Element => {
    const gradientId =
        metric === "daily_active_users" ? "fillAdoptionDaily" : "fillAdoptionMonthly";

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
                            dataKey="date"
                            minTickGap={32}
                            tickFormatter={(value: string) =>
                                tickFormatter.format(parseAdoptionDate(value))
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
                                    indicator="dot"
                                    labelFormatter={(value) =>
                                        typeof value === "string"
                                            ? tooltipFormatter.format(
                                                  parseAdoptionDate(value),
                                              )
                                            : ""
                                    }
                                />
                            }
                            cursor={false}
                        />
                        <Area
                            dataKey={metric}
                            fill={`url(#${gradientId})`}
                            stroke={`var(--color-${metric})`}
                            type="natural"
                        />
                    </AreaChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
