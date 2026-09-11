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
    ChartInteractivePoint,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { formatLocaleNumber } from "../../lib/number-format";
import {
    formatTimeSeriesTick,
    formatTimeSeriesTooltipLabel,
    type TimeGranularity,
    timeGranularityLabel,
} from "../../lib/time-series";
import type { ChatAnalyticsTimeSeriesPoint } from "../types";

interface ChatVolumeChartProps {
    canInspect: boolean;
    onInspect: (point: ChatAnalyticsTimeSeriesPoint) => void;
    data: ChatAnalyticsTimeSeriesPoint[];
    granularity: TimeGranularity;
}

type VolumeMetric = "conversations" | "turns";

interface VolumeLineChartProps extends ChatVolumeChartProps {
    config: ChartConfig;
    dataKey: VolumeMetric;
    title: string;
    description: string;
}

const chatsChartConfig = {
    conversations: {
        label: "Chats",
        color: "var(--chart-1)",
    },
} satisfies ChartConfig;

const turnsChartConfig = {
    turns: {
        label: "Turns",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

const VolumeLineChart = ({
    canInspect,
    onInspect,
    data,
    config,
    dataKey,
    title,
    description,
    granularity,
}: VolumeLineChartProps): JSX.Element => (
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
                <LineChart
                    accessibilityLayer
                    data={data}
                    onClick={
                        canInspect
                            ? (state): void => {
                                  const point = data.find(
                                      (item) =>
                                          item.bucket_start ===
                                          state.activeLabel,
                                  );
                                  if (point !== undefined) {
                                      onInspect(point);
                                  }
                              }
                            : undefined
                    }
                    style={{ cursor: canInspect ? "pointer" : "default" }}
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
                    <Line
                        connectNulls={false}
                        dataKey={dataKey}
                        dot={
                            canInspect || data.length === 1 ? (
                                <ChartInteractivePoint
                                    canActivate={canInspect}
                                    getActionLabel={(index) => {
                                        const point = data[index];
                                        return point === undefined
                                            ? undefined
                                            : `Open ${dataKey === "conversations" ? "chats" : "turns"}: ${formatLocaleNumber(point[dataKey])} · ${formatTimeSeriesTooltipLabel(point.bucket_start, granularity)}`;
                                    }}
                                    itemCount={data.length}
                                    markerColor={
                                        data.length === 1
                                            ? `var(--color-${dataKey})`
                                            : undefined
                                    }
                                    onActivate={(index) => {
                                        const point = data[index];
                                        if (point !== undefined) {
                                            onInspect(point);
                                        }
                                    }}
                                />
                            ) : (
                                false
                            )
                        }
                        isAnimationActive={false}
                        stroke={`var(--color-${dataKey})`}
                        strokeWidth={2}
                        type="linear"
                    />
                </LineChart>
            </ChartContainer>
        </CardContent>
    </Card>
);

export const ChatVolumeChart = ({
    canInspect,
    onInspect,
    data,
    granularity,
}: ChatVolumeChartProps): JSX.Element => (
    <VolumeLineChart
        canInspect={canInspect}
        config={chatsChartConfig}
        data={data}
        dataKey="conversations"
        description={`${timeGranularityLabel[granularity]} chat starts`}
        granularity={granularity}
        onInspect={onInspect}
        title="Chats over time"
    />
);

export const TurnsVolumeChart = ({
    canInspect,
    onInspect,
    data,
    granularity,
}: ChatVolumeChartProps): JSX.Element => (
    <VolumeLineChart
        canInspect={canInspect}
        config={turnsChartConfig}
        data={data}
        dataKey="turns"
        description={`${timeGranularityLabel[granularity]} turns in selected chats`}
        granularity={granularity}
        onInspect={onInspect}
        title="Turns over time"
    />
);
