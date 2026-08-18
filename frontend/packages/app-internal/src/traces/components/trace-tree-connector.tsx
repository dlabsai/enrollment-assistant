import { cn } from "@va/shared/lib/utils";
import type { JSX } from "react";

const buildConnectorSlots = (
    ancestorContinuations: boolean[],
): { continues: boolean; key: string }[] =>
    ancestorContinuations.map((continues, index) => ({
        continues,
        key: ancestorContinuations
            .slice(0, index + 1)
            .map((value) => (value ? "1" : "0"))
            .join(""),
    }));

export const TraceTreeConnector = ({
    ancestorContinuations,
    depth,
    hasChildren,
    isCollapsed,
    isLastSibling,
}: {
    ancestorContinuations: boolean[];
    depth: number;
    hasChildren: boolean;
    isCollapsed: boolean;
    isLastSibling: boolean;
}): JSX.Element => (
    <span
        aria-hidden
        className="flex h-full shrink-0 self-stretch"
    >
        {buildConnectorSlots(ancestorContinuations).map((slot) => (
            <span
                className="relative h-full w-3.5 shrink-0"
                key={slot.key}
            >
                {slot.continues ? (
                    <span className="trace-tree-line absolute inset-y-0 left-1/2 border-l" />
                ) : undefined}
            </span>
        ))}
        {depth > 0 ? (
            <span className="relative h-full w-3.5 shrink-0">
                <span
                    className={cn(
                        "trace-tree-line absolute top-0 left-1/2 border-l",
                        isLastSibling ? "h-1/2" : "bottom-0",
                    )}
                />
                <span className="trace-tree-line absolute top-1/2 right-0 left-1/2 border-t" />
            </span>
        ) : undefined}
        <span className="relative h-full w-3.5 shrink-0">
            <span
                className={cn(
                    "trace-tree-line absolute top-1/2 right-0 border-t",
                    depth === 0 ? "left-1/2" : "left-0",
                )}
            />
            {hasChildren && !isCollapsed ? (
                <span className="trace-tree-line absolute top-1/2 bottom-0 left-1/2 border-l" />
            ) : undefined}
        </span>
        <span className="relative h-full w-1.5 shrink-0">
            <span className="trace-tree-line absolute inset-x-0 top-1/2 border-t" />
        </span>
    </span>
);
