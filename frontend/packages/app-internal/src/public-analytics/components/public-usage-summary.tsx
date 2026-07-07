import { IconMail } from "@tabler/icons-react";
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
import type { PublicUsageSummary } from "../../usage/types";

interface PublicUsageSummaryProps {
    summary: PublicUsageSummary;
}

const cardGridClassName =
    "*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs";

export const PublicUsageSummaryCards = ({
    summary,
}: PublicUsageSummaryProps): JSX.Element => (
    <div className={cardGridClassName}>
        <Card className="@container/card">
            <CardHeader>
                <CardDescription>Total leads</CardDescription>
                <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
                    {formatLocaleNumber(summary.total_leads)}
                </CardTitle>
                <CardAction>
                    <IconMail className="text-muted-foreground size-5" />
                </CardAction>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">
                Unique captured emails
            </CardContent>
        </Card>
    </div>
);
