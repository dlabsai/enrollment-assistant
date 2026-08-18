import { Badge } from "@va/shared/components/ui/badge";
import { cn } from "@va/shared/lib/utils";
import { CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import type { JSX } from "react";

import type { TraceOutcome } from "../types";

interface TraceOutcomeBadgeProps {
    outcome: TraceOutcome | null | undefined;
    failedResultCount?: number;
    className?: string;
}

const getTraceOutcomeLabel = (
    outcome: TraceOutcome,
    failedResultCount: number | undefined,
): string => {
    if (outcome === "error") {
        return "Error";
    }
    if (outcome === "fail") {
        return failedResultCount !== undefined && failedResultCount > 0
            ? `${failedResultCount} failed`
            : "Failed";
    }
    return "Passed";
};

export const TraceOutcomeIndicator = ({
    outcome,
    failedResultCount,
    className,
}: TraceOutcomeBadgeProps): JSX.Element | null => {
    if (outcome === null || outcome === undefined) {
        return null;
    }

    const label = getTraceOutcomeLabel(outcome, failedResultCount);
    const Icon =
        outcome === "error"
            ? TriangleAlert
            : outcome === "fail"
              ? CircleX
              : CircleCheck;

    return (
        <span
            aria-label={label}
            className={cn(
                "flex size-4 shrink-0 items-center justify-center",
                outcome === "error"
                    ? "text-amber-700 dark:text-amber-400"
                    : outcome === "fail"
                      ? "text-destructive"
                      : "text-emerald-700 dark:text-emerald-400",
                className,
            )}
            role="img"
            title={label}
        >
            <Icon aria-hidden className="size-3.5" />
        </span>
    );
};

export const TraceOutcomeBadge = ({
    outcome,
    failedResultCount,
    className,
}: TraceOutcomeBadgeProps): JSX.Element | null => {
    if (outcome === null || outcome === undefined) {
        return null;
    }

    if (outcome === "error") {
        return (
            <Badge
                className={cn(
                    "border-amber-600/20 bg-amber-500/10 text-amber-700 dark:text-amber-400",
                    className,
                )}
                variant="outline"
            >
                <TriangleAlert data-icon="inline-start" />
                Error
            </Badge>
        );
    }

    if (outcome === "fail") {
        return (
            <Badge className={className} variant="destructive">
                <CircleX data-icon="inline-start" />
                {getTraceOutcomeLabel(outcome, failedResultCount)}
            </Badge>
        );
    }

    return (
        <Badge
            className={cn(
                "border-emerald-600/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
                className,
            )}
            variant="outline"
        >
            <CircleCheck data-icon="inline-start" />
            Passed
        </Badge>
    );
};

export const TraceStatusBadge = ({
    isError,
    failedResultCount = 0,
}: {
    isError: boolean;
    failedResultCount?: number;
}): JSX.Element => {
    if (isError) {
        return <TraceOutcomeBadge outcome="error" />;
    }
    if (failedResultCount > 0) {
        return (
            <TraceOutcomeBadge
                failedResultCount={failedResultCount}
                outcome="fail"
            />
        );
    }
    return <Badge variant="secondary">OK</Badge>;
};
