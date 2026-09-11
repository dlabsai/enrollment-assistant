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
    timeGranularityLabel,
} from "../../lib/time-series";
import type { PublicAnalyticsTimeSeriesPoint } from "../types";

interface PublicLeadsChartProps {
    data: PublicAnalyticsTimeSeriesPoint[];
    granularity: TimeGranularity;
}

const chartConfig = {
    leads: {
        label: "Leads",
        color: "var(--chart-4)",
    },
} satisfies ChartConfig;

export const PublicLeadsChart = ({
    data,
    granularity,
}: PublicLeadsChartProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardTitle>Leads over time</CardTitle>
            <CardDescription>
                {timeGranularityLabel[granularity]} leads
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
                        dataKey="leads"
                        fill="url(#fillLeads)"
                        isAnimationActive={false}
                        stroke="var(--color-leads)"
                    />
                </AreaChart>
            </ChartContainer>
        </CardContent>
    </Card>
);
