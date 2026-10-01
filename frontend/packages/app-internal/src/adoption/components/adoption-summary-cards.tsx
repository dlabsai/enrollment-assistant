import {
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    CalendarDays,
    ChartNoAxesCombined,
    MessageSquareText,
    Percent,
    UserPlus,
    UserRoundX,
    Users,
} from "lucide-react";
import type { JSX, ReactNode } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import type { AdoptionSummary } from "../types";

interface AdoptionSummaryCardsProps {
    summary: AdoptionSummary;
}

const cardGridBaseClassName =
    "*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs";
const accountCardGridClassName = `${cardGridBaseClassName} @xl/main:grid-cols-2 @4xl/main:grid-cols-3`;
const adoptionCardGridClassName = `${cardGridBaseClassName} @xl/main:grid-cols-2 @5xl/main:grid-cols-4`;
const valueClassName =
    "text-2xl font-semibold tabular-nums @[250px]/card:text-3xl";

const formatPercent = (value: number): string =>
    formatLocaleNumber(value, {
        style: "percent",
        maximumFractionDigits: 1,
    });

const accountShare = (count: number, total: number): string =>
    formatPercent(total === 0 ? 0 : count / total);

interface SummaryCardProps {
    description: string;
    icon: ReactNode;
    title: string;
    value: string;
}

const SummaryCard = ({
    description,
    icon,
    title,
    value,
}: SummaryCardProps): JSX.Element => (
    <Card className="@container/card">
        <CardHeader>
            <CardDescription>{title}</CardDescription>
            <CardTitle className={valueClassName}>{value}</CardTitle>
            <CardAction>{icon}</CardAction>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
            {description}
        </CardContent>
    </Card>
);

export const AccountSummaryCards = ({
    summary,
}: AdoptionSummaryCardsProps): JSX.Element => {
    const inactiveNewAccounts =
        summary.new_accounts - summary.active_new_accounts;

    return (
        <section className="flex flex-col gap-3">
            <h2 className="text-lg font-semibold">New accounts</h2>
            <div className={accountCardGridClassName}>
                <SummaryCard
                    description="Created during the selected range"
                    icon={<UserPlus className="text-muted-foreground size-5" />}
                    title="Created"
                    value={formatLocaleNumber(summary.new_accounts)}
                />
                <SummaryCard
                    description={`${accountShare(
                        summary.active_new_accounts,
                        summary.new_accounts,
                    )} of new accounts`}
                    icon={
                        <MessageSquareText className="text-muted-foreground size-5" />
                    }
                    title="Used Chat"
                    value={formatLocaleNumber(summary.active_new_accounts)}
                />
                <SummaryCard
                    description={`${accountShare(
                        inactiveNewAccounts,
                        summary.new_accounts,
                    )} of new accounts`}
                    icon={
                        <UserRoundX className="text-muted-foreground size-5" />
                    }
                    title="Did not use Chat"
                    value={formatLocaleNumber(inactiveNewAccounts)}
                />
            </div>
        </section>
    );
};

export const AdoptionSummaryCards = ({
    summary,
}: AdoptionSummaryCardsProps): JSX.Element => (
    <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Adoption</h2>
        <div className={adoptionCardGridClassName}>
            <SummaryCard
                description="Active on the latest day"
                icon={<Users className="text-muted-foreground size-5" />}
                title="Daily active users"
                value={formatLocaleNumber(summary.latest_daily_active_users)}
            />
            <SummaryCard
                description="Active in the latest rolling 30 days"
                icon={<CalendarDays className="text-muted-foreground size-5" />}
                title="Monthly active users"
                value={formatLocaleNumber(summary.monthly_active_users)}
            />
            <SummaryCard
                description="Mean across the selected range"
                icon={
                    <ChartNoAxesCombined className="text-muted-foreground size-5" />
                }
                title="Average daily users"
                value={formatLocaleNumber(summary.average_daily_active_users, {
                    maximumFractionDigits: 1,
                })}
            />
            <SummaryCard
                description="Share of monthly users active on the latest day"
                icon={<Percent className="text-muted-foreground size-5" />}
                title="DAU / MAU stickiness"
                value={formatPercent(summary.stickiness)}
            />
        </div>
    </section>
);
