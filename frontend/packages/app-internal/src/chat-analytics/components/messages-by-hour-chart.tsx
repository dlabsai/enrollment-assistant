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
import type { ChatAnalyticsHourly, PublicUsageHourly } from "../../usage/types";

type MessagesByHourDatum = ChatAnalyticsHourly | PublicUsageHourly;

interface MessagesByHourChartProps {
    data: MessagesByHourDatum[];
}

const chartConfig = {
    messages: {
        label: "Messages",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

const hourFormatter = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
});

const formatHour = (hour: number): string =>
    hourFormatter.format(new Date(2000, 0, 1, hour));

const hasPayload = (value: unknown): value is { payload: unknown } =>
    typeof value === "object" && value !== null && "payload" in value;

const hasHour = (value: unknown): value is { hour: unknown } =>
    typeof value === "object" && value !== null && "hour" in value;

const isUnknownArray = (value: unknown): value is unknown[] =>
    Array.isArray(value);

const extractHourFromPayload = (payload: unknown): number | undefined => {
    if (!isUnknownArray(payload) || payload.length === 0) {
        return undefined;
    }

    const [first] = payload;

    if (!hasPayload(first)) {
        return undefined;
    }

    const rawPayload = first.payload;

    if (!hasHour(rawPayload)) {
        return undefined;
    }

    const { hour } = rawPayload;
    const hourValue = typeof hour === "number" ? hour : Number(hour);

    return Number.isFinite(hourValue) ? hourValue : undefined;
};

export const MessagesByHourChart = ({
    data,
}: MessagesByHourChartProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardTitle>Messages by hour</CardTitle>
            <CardDescription>
                When messages happen during the day
            </CardDescription>
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
                        dataKey="hour"
                        tickFormatter={(value: number) => formatHour(value)}
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
                                labelFormatter={(labelValue, payload) => {
                                    void labelValue;
                                    const hourValue =
                                        extractHourFromPayload(payload);

                                    return typeof hourValue === "number"
                                        ? `Hour ${formatHour(hourValue)}`
                                        : "Hour";
                                }}
                            />
                        }
                        cursor={false}
                    />
                    <Bar
                        dataKey="messages"
                        fill="var(--color-messages)"
                        radius={4}
                    />
                </BarChart>
            </ChartContainer>
        </CardContent>
    </Card>
);
