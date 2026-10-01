import {
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { BookOpenText, FileCheck2, MessageSquareText } from "lucide-react";
import type { JSX } from "react";

import { formatLocaleNumber } from "../../lib/number-format";
import type { ChatInsightCoverage } from "../types";

interface InsightSummaryCardsProps {
    coverage: ChatInsightCoverage;
    currentDocumentsUsed: number;
}

const cardGridClassName =
    "*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs @xl/main:grid-cols-2 @4xl/main:grid-cols-3";

export const InsightSummaryCards = ({
    coverage,
    currentDocumentsUsed,
}: InsightSummaryCardsProps): JSX.Element => (
    <div className={cardGridClassName}>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Analyzed chats</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatLocaleNumber(coverage.analyzed_chats)}
                </CardTitle>
                <CardAction>
                    <MessageSquareText className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                {coverage.classification_gaps > 0
                    ? `${formatLocaleNumber(coverage.classification_gaps)} current chats still need topic labels`
                    : "Current-branch chats in this range"}
            </CardContent>
        </Card>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Answers using documents</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatLocaleNumber(
                        coverage.document_grounded_answers,
                    )}
                </CardTitle>
                <CardAction>
                    <FileCheck2 className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Assistant replies backed by at least one document
            </CardContent>
        </Card>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Current documents used</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatLocaleNumber(currentDocumentsUsed)}
                </CardTitle>
                <CardAction>
                    <BookOpenText className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Used in this range and still available now
            </CardContent>
        </Card>
    </div>
);
