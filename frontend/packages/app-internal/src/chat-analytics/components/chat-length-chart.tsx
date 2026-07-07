import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import type { JSX } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
    type ChartConfig,
    ChartContainer,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { formatLocaleNumber } from "../../lib/number-format";
import type {
    ChatAnalyticsBucket,
    ChatAnalyticsStats,
    PublicUsageBucket,
} from "../../usage/types";

type ChatLengthBucket = ChatAnalyticsBucket | PublicUsageBucket;

interface ChatLengthChartProps {
    data: ChatLengthBucket[];
    stats?: ChatAnalyticsStats | null;
}

const chartConfig = {
    conversations: {
        label: "Chats",
        color: "var(--chart-3)",
    },
} satisfies ChartConfig;

const formatStat = (value: number | null | undefined): string => {
    if (value === null || value === undefined) {
        return "—";
    }
    return formatLocaleNumber(value, {
        minimumFractionDigits: 0,
        maximumFractionDigits: value % 1 === 0 ? 0 : 1,
    });
};

const statLabels = [
    { label: "Min", key: "min" },
    { label: "Max", key: "max" },
    { label: "Avg", key: "avg" },
    { label: "Median", key: "median" },
    { label: "P50", key: "p50" },
    { label: "P75", key: "p75" },
    { label: "P90", key: "p90" },
    { label: "P95", key: "p95" },
    { label: "P99", key: "p99" },
] as const satisfies { label: string; key: keyof ChatAnalyticsStats }[];

export const ChatLengthChart = ({
    data,
    stats,
}: ChatLengthChartProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardTitle>Chat length distribution</CardTitle>
            <CardDescription>Chats by number of messages</CardDescription>
            {stats ? (
                <div className="text-muted-foreground mt-3 grid grid-cols-3 gap-3 text-xs sm:grid-cols-6">
                    {statLabels.map(({ label, key }) => (
                        <div
                            className="flex flex-col gap-0.5"
                            key={label}
                        >
                            <span>{label}</span>
                            <span className="text-foreground font-medium tabular-nums">
                                {formatStat(stats[key])}
                            </span>
                        </div>
                    ))}
                </div>
            ) : undefined}
        </CardHeader>
        <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
            <ChartContainer
                className="aspect-auto h-[250px] w-full"
                config={chartConfig}
            >
                <BarChart data={data}>
                    <CartesianGrid vertical={false} />
                    <XAxis
                        axisLine={false}
                        dataKey="label"
                        tickLine={false}
                        tickMargin={8}
                    />
                    <YAxis
                        axisLine={false}
                        tickLine={false}
                        width={48}
                    />
                    <ChartTooltip
                        content={
                            <ChartTooltipContent
                                formatter={(value) =>
                                    typeof value === "number"
                                        ? formatLocaleNumber(value)
                                        : value
                                }
                            />
                        }
                        cursor={false}
                    />
                    <Bar
                        dataKey="conversations"
                        fill="var(--color-conversations)"
                        radius={4}
                    />
                </BarChart>
            </ChartContainer>
        </CardContent>
    </Card>
);
