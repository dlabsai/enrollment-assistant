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
    ChartLegend,
    ChartLegendContent,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import type { TimeRangeValue } from "../../lib/time-range";
import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    isHourlyTimeRange,
} from "../../lib/time-series";
import type { ChatAnalyticsDaily } from "../../usage/types";

interface ChatVolumeChartProps {
    data: ChatAnalyticsDaily[];
    timeRange: TimeRangeValue;
}

type VolumeMetric = "conversations" | "messages";

interface VolumeAreaChartProps {
    data: ChatAnalyticsDaily[];
    config: ChartConfig;
    dataKey: VolumeMetric;
    title: string;
    description: string;
    gradientId: string;
    timeRange: TimeRangeValue;
}

const chatsChartConfig = {
    conversations: {
        label: "Chats",
        color: "var(--chart-1)",
    },
} satisfies ChartConfig;

const messagesChartConfig = {
    messages: {
        label: "Messages",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

const VolumeAreaChart = ({
    data,
    config,
    dataKey,
    title,
    description,
    gradientId,
    timeRange,
}: VolumeAreaChartProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
            <ChartContainer
                className="aspect-auto h-[250px] w-full"
                config={config}
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
                                stopColor={`var(--color-${dataKey})`}
                                stopOpacity={1}
                            />
                            <stop
                                offset="95%"
                                stopColor={`var(--color-${dataKey})`}
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
                        dataKey={dataKey}
                        fill={`url(#${gradientId})`}
                        stroke={`var(--color-${dataKey})`}
                        type="natural"
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

export const ChatVolumeChart = ({
    data,
    timeRange,
}: ChatVolumeChartProps): JSX.Element => (
    <VolumeAreaChart
        config={chatsChartConfig}
        data={data}
        dataKey="conversations"
        description={
            isHourlyTimeRange(timeRange) ? "Hourly chats" : "Daily chats"
        }
        gradientId="fillChats"
        timeRange={timeRange}
        title="Chats over time"
    />
);

export const MessagesVolumeChart = ({
    data,
    timeRange,
}: ChatVolumeChartProps): JSX.Element => (
    <VolumeAreaChart
        config={messagesChartConfig}
        data={data}
        dataKey="messages"
        description={
            isHourlyTimeRange(timeRange) ? "Hourly messages" : "Daily messages"
        }
        gradientId="fillMessages"
        timeRange={timeRange}
        title="Messages over time"
    />
);
