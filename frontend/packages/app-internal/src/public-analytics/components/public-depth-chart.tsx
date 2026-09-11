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

import type { PublicAnalyticsSummary } from "../types";

interface PublicDepthChartProps {
    data: PublicAnalyticsSummary["depth_buckets"];
}

const chartConfig = {
    conversations: {
        label: "Public chats",
        color: "var(--chart-3)",
    },
} satisfies ChartConfig;

export const PublicDepthChart = ({
    data,
}: PublicDepthChartProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardTitle>Public chat depth</CardTitle>
            <CardDescription>Chats by number of messages</CardDescription>
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
                        allowDecimals={false}
                        axisLine={false}
                        tickLine={false}
                        width={48}
                    />
                    <ChartTooltip
                        content={<ChartTooltipContent />}
                        cursor={<ChartCategoryCursor />}
                    />
                    <Bar
                        dataKey="conversations"
                        fill="var(--color-conversations)"
                        isAnimationActive={false}
                        radius={4}
                    />
                </BarChart>
            </ChartContainer>
        </CardContent>
    </Card>
);
