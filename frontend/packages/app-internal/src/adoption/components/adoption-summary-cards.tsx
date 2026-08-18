import {
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { CalendarDays, ChartNoAxesCombined, Percent, Users } from "lucide-react";
import type { JSX } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import type { AdoptionSummary } from "../types";

interface AdoptionSummaryCardsProps {
    summary: AdoptionSummary;
}

const cardGridClassName =
    "*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs @xl/main:grid-cols-2 @5xl/main:grid-cols-4";
const valueClassName =
    "text-2xl font-semibold tabular-nums @[250px]/card:text-3xl";

export const AdoptionSummaryCards = ({
    summary,
}: AdoptionSummaryCardsProps): JSX.Element => (
    <div className={cardGridClassName}>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Daily active users</CardDescription>
                <CardTitle className={valueClassName}>
                    {formatLocaleNumber(summary.latest_daily_active_users)}
                </CardTitle>
                <CardAction>
                    <Users className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Active on the latest day
            </CardContent>
        </Card>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Monthly active users</CardDescription>
                <CardTitle className={valueClassName}>
                    {formatLocaleNumber(summary.monthly_active_users)}
                </CardTitle>
                <CardAction>
                    <CalendarDays className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Active in the latest rolling 30 days
            </CardContent>
        </Card>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Average daily users</CardDescription>
                <CardTitle className={valueClassName}>
                    {formatLocaleNumber(summary.average_daily_active_users, {
                        maximumFractionDigits: 1,
                    })}
                </CardTitle>
                <CardAction>
                    <ChartNoAxesCombined className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Mean across the selected range
            </CardContent>
        </Card>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>DAU / MAU stickiness</CardDescription>
                <CardTitle className={valueClassName}>
                    {formatLocaleNumber(summary.stickiness, {
                        style: "percent",
                        maximumFractionDigits: 1,
                    })}
                </CardTitle>
                <CardAction>
                    <Percent className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Share of monthly users active on the latest day
            </CardContent>
        </Card>
    </div>
);
