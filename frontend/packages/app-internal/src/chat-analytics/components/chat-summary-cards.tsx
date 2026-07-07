import { IconChartLine, IconMessage, IconMessages } from "@tabler/icons-react";
import {
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import type { JSX } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import type { ChatAnalyticsSummary } from "../../usage/types";

interface ChatSummaryCardsProps {
    summary: ChatAnalyticsSummary;
}

const formatAvg = (value: number): string =>
    formatLocaleNumber(value, {
        maximumFractionDigits: value % 1 === 0 ? 0 : 1,
    });

const cardGridClassName =
    "*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs @xl/main:grid-cols-2 @4xl/main:grid-cols-3";

export const ChatSummaryCards = ({
    summary,
}: ChatSummaryCardsProps): JSX.Element => (
    <div className={cardGridClassName}>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Total chats</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatLocaleNumber(summary.total_conversations)}
                </CardTitle>
                <CardAction>
                    <IconMessage className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Chats in this view
            </CardContent>
        </Card>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Total messages</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatLocaleNumber(summary.total_messages)}
                </CardTitle>
                <CardAction>
                    <IconMessages className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                User and assistant messages
            </CardContent>
        </Card>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Avg messages per chat</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatAvg(summary.avg_messages_per_conversation)}
                </CardTitle>
                <CardAction>
                    <IconChartLine className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Average chat length
            </CardContent>
        </Card>
    </div>
);
