import { Button } from "@va/shared/components/ui/button";
import { ChevronsDown, ChevronsUp } from "lucide-react";
import { type JSX, useMemo } from "react";

import type { TraceCollapseControls } from "../hooks/use-trace-collapse";

export const TraceCollapseAllButton = ({
    collapseControls,
    expandableSpanIds,
}: {
    collapseControls: TraceCollapseControls;
    expandableSpanIds: ReadonlySet<string>;
}): JSX.Element => {
    const { collapsedSpanIds, setSpansCollapsed } = collapseControls;
    const hasCollapsedSpans = useMemo(
        () =>
            [...expandableSpanIds].some((spanId) =>
                collapsedSpanIds.has(spanId),
            ),
        [collapsedSpanIds, expandableSpanIds],
    );

    return (
        <Button
            aria-label={
                hasCollapsedSpans
                    ? "Expand all spans"
                    : "Collapse all spans"
            }
            disabled={expandableSpanIds.size === 0}
            onClick={() => {
                setSpansCollapsed(expandableSpanIds, !hasCollapsedSpans);
            }}
            size="icon-sm"
            type="button"
            variant="outline"
        >
            {hasCollapsedSpans ? <ChevronsDown /> : <ChevronsUp />}
        </Button>
    );
};
