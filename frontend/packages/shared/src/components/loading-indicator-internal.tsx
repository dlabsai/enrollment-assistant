import { Loader } from "@va/shared/components/ai-elements/loader";
import {
    Reasoning,
    ReasoningContent,
    ReasoningTrigger,
} from "@va/shared/components/ai-elements/reasoning";
import { Shimmer } from "@va/shared/components/ai-elements/shimmer";
import {
    Tool,
    ToolContent,
    ToolHeader,
    ToolInput,
    ToolOutput,
} from "@va/shared/components/ai-elements/tool";
import { cn } from "@va/shared/lib/utils";
import type {
    LoadingActivityLogEntry,
    LoadingIndicatorProps,
} from "@va/shared/types";
import { type JSX, useEffect, useMemo, useRef, useState } from "react";

const serializeActivityValue = (value: unknown): string => {
    if (value === undefined) {
        return "";
    }
    if (typeof value === "string") {
        return value;
    }
    if (typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }
    try {
        return JSON.stringify(value);
    } catch {
        return Object.prototype.toString.call(value);
    }
};

export const LoadingIndicator = ({
    isVisible,
    onTextShow,
    messages,
    activityItems,
    activityLog,
    variant = "default",
    showHeader = true,
    showEmptyState = true,
}: LoadingIndicatorProps): JSX.Element | undefined => {
    void messages;
    const useAiElements = variant === "ai-elements";
    const resolvedActivityItems = useAiElements
        ? (activityItems ?? [])
        : (activityItems ?? []).filter((item) => item.kind !== "thinking");
    const hasActivity = resolvedActivityItems.length > 0;
    const useShimmer = variant === "shimmer";
    const onTextShowRef = useRef(onTextShow);

    useEffect(() => {
        onTextShowRef.current = onTextShow;
    }, [onTextShow]);

    const activitySignature = resolvedActivityItems
        .map((item) => {
            const toolSignature = [
                item.kind ?? "",
                item.toolState ?? "",
                item.toolName ?? "",
                serializeActivityValue(item.toolInput),
                serializeActivityValue(item.toolOutput),
                item.toolErrorText ?? "",
                item.thinkingContent ?? "",
            ].join(":");
            return `${item.id}:${item.status}:${item.label}:${item.parentId ?? ""}:${toolSignature}`;
        })
        .join("|");

    useEffect(() => {
        if (!isVisible || hasActivity) {
            return;
        }
        onTextShowRef.current?.();
    }, [hasActivity, isVisible]);

    useEffect(() => {
        if (!isVisible || !hasActivity) {
            return;
        }
        onTextShowRef.current?.();
    }, [activitySignature, hasActivity, isVisible]);

    const logEntries = useMemo(
        () =>
            (activityLog ?? []).toSorted(
                (left, right) => left.sequence - right.sequence,
            ),
        [activityLog],
    );

    const hasActiveAgent =
        useAiElements &&
        logEntries.some(
            (entry) =>
                entry.kind === "agent" &&
                entry.status === "in_progress" &&
                entry.startedAtMs !== undefined,
        );

    const [timeTick, setTimeTick] = useState(() => Date.now());

    useEffect((): (() => void) | undefined => {
        if (!hasActiveAgent) {
            return undefined;
        }

        const interval = setInterval(() => {
            setTimeTick(Date.now());
        }, 1000);

        return () => {
            clearInterval(interval);
        };
    }, [hasActiveAgent]);

    if (!isVisible) {
        return undefined;
    }

    if (useAiElements) {
        const hasLogEntries = logEntries.length > 0;

        if (!hasLogEntries && !showEmptyState) {
            return undefined;
        }

        const renderToolEntry = (
            entry: LoadingActivityLogEntry,
        ): JSX.Element => {
            const toolState =
                entry.toolState ??
                (entry.status === "in_progress"
                    ? "input-available"
                    : entry.status === "error"
                      ? "output-error"
                      : "output-available");
            const toolName = entry.toolName ?? entry.label;

            return (
                <Tool defaultOpen={false}>
                    <ToolHeader
                        state={toolState}
                        title={toolName}
                        toolName={toolName}
                        type="dynamic-tool"
                    />
                    <ToolContent>
                        {entry.toolInput !== undefined && (
                            <ToolInput input={entry.toolInput} />
                        )}
                        <ToolOutput
                            errorText={entry.toolErrorText}
                            output={entry.toolOutput}
                        />
                    </ToolContent>
                </Tool>
            );
        };

        const renderReasoningEntry = (
            entry: LoadingActivityLogEntry,
        ): JSX.Element | undefined => {
            const content = entry.thinkingContent?.trim() ?? "";
            if (content.length === 0) {
                return undefined;
            }

            return (
                <Reasoning
                    defaultOpen={entry.status === "in_progress"}
                    isStreaming={entry.status === "in_progress"}
                >
                    <ReasoningTrigger />
                    <ReasoningContent>{content}</ReasoningContent>
                </Reasoning>
            );
        };

        const formatDuration = (durationMs: number): string => {
            const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = totalSeconds % 60;
            if (minutes > 0) {
                return `${minutes}:${seconds.toString().padStart(2, "0")}`;
            }
            return `${totalSeconds}s`;
        };

        const renderEntry = (
            entry: LoadingActivityLogEntry,
        ): JSX.Element | undefined => {
            const wrapperClass = cn(
                "flex flex-col gap-2",
                entry.parentId === undefined ? undefined : "pl-4",
            );

            switch (entry.kind) {
                case "agent": {
                    const nowMs = timeTick;
                    const durationMs =
                        entry.durationMs ??
                        (entry.startedAtMs === undefined
                            ? undefined
                            : nowMs - entry.startedAtMs);
                    const durationText =
                        durationMs === undefined
                            ? undefined
                            : formatDuration(durationMs);

                    return (
                        <div className={wrapperClass}>
                            <div className="text-foreground flex items-center gap-2 text-sm font-medium">
                                {entry.status === "in_progress" ? (
                                    <Shimmer className="text-sm">
                                        {entry.label}
                                    </Shimmer>
                                ) : (
                                    entry.label
                                )}
                                {durationText !== undefined && (
                                    <span className="text-muted-foreground text-sm tabular-nums">
                                        {durationText}
                                    </span>
                                )}
                            </div>
                        </div>
                    );
                }
                case "thinking": {
                    const reasoning = renderReasoningEntry(entry);
                    if (reasoning === undefined) {
                        return undefined;
                    }
                    return <div className={wrapperClass}>{reasoning}</div>;
                }
                case "tool": {
                    return (
                        <div className={wrapperClass}>
                            {renderToolEntry(entry)}
                        </div>
                    );
                }
                default: {
                    return (
                        <div className={wrapperClass}>
                            <span className="text-muted-foreground text-sm">
                                {entry.label}
                            </span>
                        </div>
                    );
                }
            }
        };

        return (
            <div className="text-primary flex flex-col gap-3 p-3 text-base">
                {showHeader && (
                    <div className="text-muted-foreground flex items-center gap-2 text-sm">
                        <Loader
                            className="text-primary"
                            size={16}
                        />
                        <span>Working...</span>
                    </div>
                )}
                {hasLogEntries ? (
                    <div className="flex flex-col gap-3">
                        {logEntries.map((entry) => (
                            <div key={entry.id}>{renderEntry(entry)}</div>
                        ))}
                    </div>
                ) : showEmptyState ? (
                    <span className="text-muted-foreground text-sm">
                        Thinking...
                    </span>
                ) : undefined}
            </div>
        );
    }

    if (hasActivity) {
        return (
            <div className="text-primary flex items-start gap-3 p-3 text-base">
                {!useShimmer && (
                    <div className="bg-primary mt-1 h-[1em] w-[1em] flex-shrink-0 animate-pulse rounded-full" />
                )}
                <div className="space-y-2">
                    {resolvedActivityItems.map((item) => {
                        const isActive = item.status === "in_progress";
                        const isComplete = item.status === "complete";
                        const isError = item.status === "error";
                        const isChild = item.parentId !== undefined;
                        const labelClassName = cn(
                            "text-sm",
                            isComplete && "text-muted-foreground opacity-70",
                            isError && "text-destructive",
                            isChild &&
                                "transition-all duration-700 ease-in-out",
                            isChild &&
                                !isComplete &&
                                !isError &&
                                "text-primary opacity-100",
                        );

                        return (
                            <div
                                className={cn(
                                    "flex items-start gap-2",
                                    isChild && "pl-4",
                                    isChild &&
                                        "transition-opacity duration-500 ease-out",
                                    isChild && "loading-fade-in",
                                )}
                                key={item.id}
                            >
                                {!useShimmer && (
                                    <span
                                        className={cn(
                                            "mt-1 h-2 w-2 rounded-full",
                                            isActive &&
                                                "bg-primary animate-pulse",
                                            isComplete && "bg-primary/40",
                                            isError && "bg-destructive",
                                        )}
                                    />
                                )}
                                {useShimmer && isActive && !isChild ? (
                                    <Shimmer className={labelClassName}>
                                        {item.label}
                                    </Shimmer>
                                ) : (
                                    <span className={labelClassName}>
                                        {item.label}
                                    </span>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    }

    return (
        <span className="text-primary flex items-start gap-3 p-3 text-base">
            {!useShimmer && (
                <div className="bg-primary mt-1 h-[1em] w-[1em] flex-shrink-0 animate-pulse rounded-full" />
            )}
            {useShimmer ? (
                <Shimmer className="text-sm">Working...</Shimmer>
            ) : (
                <span className="text-sm">Working...</span>
            )}
        </span>
    );
};
