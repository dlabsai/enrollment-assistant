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
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart";

import { formatLocaleNumber } from "../../lib/number-format";
import { getAppFormatSettings } from "../../lib/time-zone";
import type { ChatAnalyticsHourly } from "../types";

interface TurnsByHourChartProps {
    data: ChatAnalyticsHourly[];
}

const appFormatSettings = getAppFormatSettings();

const chartConfig = {
    turns: {
        label: "Turns",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

const hourFormatter = new Intl.DateTimeFormat(appFormatSettings.locale, {
    hour: "numeric",
});

const formatHour = (hour: number): string =>
    hourFormatter.format(new Date(2000, 0, 1, hour));

export const TurnsByHourChart = ({
    data,
}: TurnsByHourChartProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardTitle>Turns by hour</CardTitle>
            <CardDescription>When turns start during the day</CardDescription>
        </CardHeader>
        <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
            <ChartContainer
                className="aspect-auto h-[250px] w-full"
                config={chartConfig}
            >
                <BarChart
                    accessibilityLayer
                    data={data}
                >
                    <CartesianGrid vertical={false} />
                    <XAxis
                        axisLine={false}
                        dataKey="hour"
                        tickFormatter={(value: number) => formatHour(value)}
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
                                labelFormatter={(hour) =>
                                    typeof hour === "number"
                                        ? `Hour ${formatHour(hour)}`
                                        : "Hour"
                                }
                            />
                        }
                        cursor={<ChartCategoryCursor />}
                    />
                    <Bar
                        dataKey="turns"
                        fill="var(--color-turns)"
                        isAnimationActive={false}
                        radius={4}
                    />
                </BarChart>
            </ChartContainer>
        </CardContent>
    </Card>
);
