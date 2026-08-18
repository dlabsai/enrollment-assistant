import { useCallback, useMemo, useState } from "react";

export interface TraceCollapseControls {
    collapsedSpanIds: ReadonlySet<string>;
    setSpansCollapsed: (
        spanIds: ReadonlySet<string>,
        collapsed: boolean,
    ) => void;
    toggleSpan: (spanId: string) => void;
}

export const useTraceCollapse = (): TraceCollapseControls => {
    const [collapsedSpanIds, setCollapsedSpanIds] = useState<Set<string>>(
        () => new Set(),
    );

    const toggleSpan = useCallback((spanId: string): void => {
        setCollapsedSpanIds((previous) => {
            const next = new Set(previous);
            if (next.has(spanId)) {
                next.delete(spanId);
            } else {
                next.add(spanId);
            }
            return next;
        });
    }, []);

    const setSpansCollapsed = useCallback(
        (spanIds: ReadonlySet<string>, collapsed: boolean): void => {
            setCollapsedSpanIds((previous) => {
                const next = new Set(previous);
                for (const spanId of spanIds) {
                    if (collapsed) {
                        next.add(spanId);
                    } else {
                        next.delete(spanId);
                    }
                }
                return next;
            });
        },
        [],
    );

    return useMemo(
        () => ({ collapsedSpanIds, setSpansCollapsed, toggleSpan }),
        [collapsedSpanIds, setSpansCollapsed, toggleSpan],
    );
};
