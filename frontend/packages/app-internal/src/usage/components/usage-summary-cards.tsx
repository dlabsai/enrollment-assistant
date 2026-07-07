import {
    IconClock,
    IconCoin,
    IconMessage,
    IconSearch,
} from "@tabler/icons-react";
import {
    Card,
    CardAction,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import type { JSX } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import { formatUsageCost, formatUsageDuration } from "../lib/formatters";
import type { UsageSummary } from "../types";

interface UsageSummaryCardsProps {
    summary: UsageSummary;
}

const cardGridClassName =
    "*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs @lg/main:grid-cols-3";

export const LlmSummaryCards = ({
    summary,
}: UsageSummaryCardsProps): JSX.Element => (
    <div className={cardGridClassName}>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>LLM requests</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatLocaleNumber(summary.totalRequests)}
                </CardTitle>
                <CardAction>
                    <IconMessage className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardFooter className="flex-col items-start gap-1.5 text-sm">
                <div className="line-clamp-1 flex gap-2 font-medium">
                    {formatLocaleNumber(summary.totalTokens)} tokens used
                </div>
                <div className="text-muted-foreground">
                    Input + output tokens
                </div>
            </CardFooter>
        </Card>

        <Card className="@container/card">
            <CardHeader>
                <CardDescription>LLM cost</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatUsageCost(summary.totalCost)}
                </CardTitle>
                <CardAction>
                    <IconCoin className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardFooter className="flex-col items-start gap-1.5 text-sm">
                <div className="line-clamp-1 flex items-center gap-2 font-medium">
                    LLM API costs
                </div>
                <div className="text-muted-foreground">
                    Based on token usage
                </div>
            </CardFooter>
        </Card>

        <Card className="@container/card">
            <CardHeader>
                <CardDescription>LLM response time</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatUsageDuration(summary.avgDuration)}
                </CardTitle>
                <CardAction>
                    <IconClock className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardFooter className="flex-col items-start gap-1.5 text-sm">
                <div className="line-clamp-1 flex gap-2 font-medium">
                    Average response latency
                </div>
                <div className="text-muted-foreground">Across LLM requests</div>
            </CardFooter>
        </Card>
    </div>
);

export const EmbeddingSummaryCards = ({
    summary,
}: UsageSummaryCardsProps): JSX.Element => (
    <div className={cardGridClassName}>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Embedding requests</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatLocaleNumber(summary.totalEmbeddingRequests)}
                </CardTitle>
                <CardAction>
                    <IconSearch className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardFooter className="flex-col items-start gap-1.5 text-sm">
                <div className="line-clamp-1 flex gap-2 font-medium">
                    {formatLocaleNumber(summary.totalEmbeddingTokens)} tokens used
                </div>
                <div className="text-muted-foreground">Input tokens</div>
            </CardFooter>
        </Card>

        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Embedding cost</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatUsageCost(summary.totalEmbeddingCost)}
                </CardTitle>
                <CardAction>
                    <IconCoin className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardFooter className="flex-col items-start gap-1.5 text-sm">
                <div className="line-clamp-1 flex gap-2 font-medium">
                    Embedding API costs
                </div>
                <div className="text-muted-foreground">
                    Based on token usage
                </div>
            </CardFooter>
        </Card>

        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Embedding response time</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatUsageDuration(summary.totalEmbeddingAvgDuration)}
                </CardTitle>
                <CardAction>
                    <IconClock className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardFooter className="flex-col items-start gap-1.5 text-sm">
                <div className="line-clamp-1 flex gap-2 font-medium">
                    Average response latency
                </div>
                <div className="text-muted-foreground">
                    Across embedding requests
                </div>
            </CardFooter>
        </Card>
    </div>
);
