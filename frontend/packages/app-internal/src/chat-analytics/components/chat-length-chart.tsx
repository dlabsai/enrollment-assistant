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
    ChartCategoryCursor,
    type ChartConfig,
    ChartContainer,
    ChartInteractiveBar,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { formatLocaleNumber } from "../../lib/number-format";
import type { ChatAnalyticsBucket, ChatAnalyticsStats } from "../types";

interface ChatLengthChartProps {
    canInspect: boolean;
    data: ChatAnalyticsBucket[];
    onInspect: (bucket: ChatAnalyticsBucket) => void;
    stats?: ChatAnalyticsStats | null;
}

const chartConfig = {
    conversations: {
        label: "Chats",
        color: "var(--chart-3)",
    },
} satisfies ChartConfig;

const getBucketActionLabel = (bucket: ChatAnalyticsBucket): string => {
    const chatCount = `${formatLocaleNumber(bucket.conversations)} ${
        bucket.conversations === 1 ? "chat" : "chats"
    }`;
    const turnCount =
        bucket.max_turns === null
            ? `${formatLocaleNumber(bucket.min_turns)} or more turns`
            : `${formatLocaleNumber(bucket.min_turns)} ${
                  bucket.min_turns === 1 ? "turn" : "turns"
              }`;
    return `Open ${chatCount} with ${turnCount}`;
};

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
    { label: "Median", key: "p50" },
    { label: "P75", key: "p75" },
    { label: "P90", key: "p90" },
    { label: "P95", key: "p95" },
    { label: "P99", key: "p99" },
] as const satisfies { label: string; key: keyof ChatAnalyticsStats }[];

export const ChatLengthChart = ({
    canInspect,
    data,
    onInspect,
    stats,
}: ChatLengthChartProps): JSX.Element => {
    const chartData = data.map((bucket) => ({
        ...bucket,
        displayLabel:
            bucket.max_turns === null
                ? `≥${formatLocaleNumber(bucket.min_turns)}`
                : formatLocaleNumber(bucket.min_turns),
    }));

    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>Chat length distribution</CardTitle>
                <CardDescription>Chats by number of turns</CardDescription>
                {stats ? (
                    <div className="text-muted-foreground mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4 lg:grid-cols-8">
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
                    <BarChart
                        accessibilityLayer
                        data={chartData}
                    >
                        <CartesianGrid vertical={false} />
                        <XAxis
                            axisLine={false}
                            dataKey="displayLabel"
                            tickLine={false}
                            tickMargin={8}
                        />
                        <YAxis
                            allowDecimals={false}
                            axisLine={false}
                            tickFormatter={(value: number) =>
                                formatLocaleNumber(value)
                            }
                            tickLine={false}
                            tickMargin={8}
                            width={48}
                        />
                        <ChartTooltip
                            content={<ChartTooltipContent />}
                            cursor={<ChartCategoryCursor />}
                            shared
                        />
                        <Bar
                            dataKey="conversations"
                            fill="var(--color-conversations)"
                            isAnimationActive={false}
                            shape={
                                <ChartInteractiveBar
                                    canActivate={canInspect}
                                    getActionLabel={(index) => {
                                        const bucket = data[index];
                                        return bucket === undefined
                                            ? undefined
                                            : getBucketActionLabel(bucket);
                                    }}
                                    itemCount={data.length}
                                    onActivate={(index) => {
                                        const bucket = data[index];
                                        if (bucket !== undefined) {
                                            onInspect(bucket);
                                        }
                                    }}
                                />
                            }
                        />
                    </BarChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
