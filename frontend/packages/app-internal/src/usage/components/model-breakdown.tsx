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
import type { ModelUsage } from "../types";

interface ModelBreakdownProps {
    data: ModelUsage[];
}

const chartConfig = {
    requests: {
        label: "Requests",
        color: "var(--chart-1)",
    },
} satisfies ChartConfig;

export const ModelBreakdown = ({ data }: ModelBreakdownProps): JSX.Element => {
    const chartData = data.slice(0, 5);

    return (
        <Card className="@container/card">
            <CardHeader>
                <CardTitle>Usage by model</CardTitle>
                <CardDescription>
                    Request count per model (top 5)
                </CardDescription>
            </CardHeader>
            <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
                <ChartContainer
                    className="aspect-auto h-[250px] w-full"
                    config={chartConfig}
                >
                    <BarChart
                        data={chartData}
                        layout="vertical"
                    >
                        <CartesianGrid horizontal={false} />
                        <YAxis
                            axisLine={false}
                            dataKey="model"
                            tickLine={false}
                            tickMargin={8}
                            type="category"
                            width={200}
                        />
                        <XAxis
                            axisLine={false}
                            tickFormatter={(value: number) =>
                                formatLocaleNumber(value)
                            }
                            tickLine={false}
                            type="number"
                        />
                        <ChartTooltip
                            content={<ChartTooltipContent />}
                            cursor={false}
                        />
                        <Bar
                            dataKey="requests"
                            fill="var(--color-requests)"
                            radius={4}
                        />
                    </BarChart>
                </ChartContainer>
            </CardContent>
        </Card>
    );
};
