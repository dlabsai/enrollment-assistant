import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
} from "@va/shared/components/ui/resizable";
import {
    handleFetchError,
    isAbortError,
    isApiError,
} from "@va/shared/lib/api-client";
import { Copy, Play, RefreshCw, StopCircle } from "lucide-react";
import {
    Fragment,
    type JSX,
    type ReactNode,
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { PageHeader } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError } from "../../components/page-state";
import { useStickyBottomScroll } from "../../lib/hooks/use-sticky-bottom-scroll";
import {
    cancelRagBuild,
    type RagOperationLogEntry,
    type RagOperationProgressEvent,
    type RagOperationProgressStepStatus,
    type RagOperationStatusEvent,
    runRagBuildStream,
    syncEvalRagStream,
} from "../lib/api";

interface RagOperationLogItem extends RagOperationLogEntry {
    id: string;
}

interface RagBuildStreamOptions {
    forceRebuild?: boolean;
    resumeExisting?: boolean;
}

interface ObserveRagBuildStreamOptions extends RagBuildStreamOptions {
    errorContext: string;
    markRunning?: boolean;
}

const RICH_TAG_CLASS_MAP: Record<string, string> = {
    blue: "text-blue-600 dark:text-blue-400",
    bold: "font-semibold",
    cyan: "text-cyan-600 dark:text-cyan-400",
    dim: "text-muted-foreground",
    green: "text-green-600 dark:text-green-400",
    magenta: "text-fuchsia-600 dark:text-fuchsia-400",
    red: "text-red-600 dark:text-red-400",
    yellow: "text-amber-600 dark:text-amber-400",
};

const normalizeRichTag = (tag: string): string =>
    tag
        .trim()
        .split(/\s+/u)
        .filter((part) => part !== "")
        .toSorted()
        .join(" ");

const resolveRichTagClassName = (tags: string[]): string => {
    const tokens = new Set(
        tags.flatMap((tag) => tag.split(/\s+/u).filter((part) => part !== "")),
    );

    return [...tokens]
        .map((token) => RICH_TAG_CLASS_MAP[token])
        .filter((className): className is string => className !== undefined)
        .join(" ");
};

const renderRichMarkup = (text: string): ReactNode[] => {
    const nodes: ReactNode[] = [];
    const tagStack: string[] = [];
    const tagPattern = /\[(?<tagContent>\/?[A-Za-z][^\]]*)\]/gu;
    let cursor = 0;
    let key = 0;

    const pushText = (value: string): void => {
        if (value === "") {
            return;
        }

        const className = resolveRichTagClassName(tagStack);
        if (className === "") {
            nodes.push(<Fragment key={`log-segment-${key}`}>{value}</Fragment>);
        } else {
            nodes.push(
                <span
                    className={className}
                    key={`log-segment-${key}`}
                >
                    {value}
                </span>,
            );
        }
        key += 1;
    };

    for (const match of text.matchAll(tagPattern)) {
        const [rawTag] = match;
        const tagContent = match.groups?.tagContent;
        const matchIndex = match.index ?? 0;

        if (tagContent !== undefined) {
            pushText(text.slice(cursor, matchIndex));

            const normalizedTag = normalizeRichTag(
                tagContent.replace(/^\//u, ""),
            );
            if (tagContent.startsWith("/")) {
                const tagIndex = tagStack.lastIndexOf(normalizedTag);
                if (tagIndex !== -1) {
                    tagStack.splice(tagIndex, 1);
                }
            } else if (normalizedTag !== "") {
                tagStack.push(normalizedTag);
            }

            cursor = matchIndex + rawTag.length;
        }
    }

    pushText(text.slice(cursor));
    return nodes;
};

const resolveStepStatusLabel = (
    status: RagOperationProgressStepStatus,
): string => {
    switch (status) {
        case "running": {
            return "Running";
        }
        case "completed": {
            return "Completed";
        }
        case "skipped": {
            return "Skipped";
        }
        case "error": {
            return "Failed";
        }
        default: {
            return "Pending";
        }
    }
};

const resolveStepStatusVariant = (
    status: RagOperationProgressStepStatus,
): "default" | "secondary" | "destructive" | "outline" => {
    switch (status) {
        case "running": {
            return "default";
        }
        case "completed": {
            return "secondary";
        }
        case "error": {
            return "destructive";
        }
        default: {
            return "outline";
        }
    }
};

export const RagPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const [isBuildRunning, setIsBuildRunning] = useState(false);
    const [isStopRequestPending, setIsStopRequestPending] = useState(false);
    const [runLogs, setRunLogs] = useState<RagOperationLogItem[]>([]);
    const [runProgress, setRunProgress] = useState<RagOperationProgressEvent>();
    const [runError, setRunError] = useState<string | undefined>();
    const [isCopyingEvalRag, setIsCopyingEvalRag] = useState(false);
    const runAbortControllerRef = useRef<AbortController | undefined>(
        undefined,
    );
    const runLogCounterRef = useRef(0);
    const {
        containerRef: runOutputContainerRef,
        handleScroll: handleRunOutputScroll,
        resetStickToBottom: resetRunOutputStickToBottom,
        scrollToBottomIfPinned: scrollRunOutputToBottomIfPinned,
    } = useStickyBottomScroll();

    const isOperationRunning =
        isBuildRunning || isStopRequestPending || isCopyingEvalRag;
    const shouldShowSteps = runProgress !== undefined;
    const shouldShowOutput = runError !== undefined || runLogs.length > 0;
    const shouldShowWorkspace = shouldShowSteps || shouldShowOutput;
    const appendLog = useCallback((entry: RagOperationLogEntry): void => {
        if (entry.stream === "command") {
            return;
        }

        runLogCounterRef.current += 1;
        setRunLogs((prev) => [
            ...prev,
            { ...entry, id: `rag-log-${runLogCounterRef.current}` },
        ]);
    }, []);

    const handleRunStatus = useCallback(
        (status: RagOperationStatusEvent): void => {
            const buildIsActive =
                status.status === "start" || status.status === "cancelling";
            setIsBuildRunning(buildIsActive);
            if (!buildIsActive) {
                setIsStopRequestPending(false);
            }
        },
        [],
    );

    const handleRunError = useCallback((message: string): void => {
        setRunError(message);
    }, []);

    const handleRunProgress = useCallback(
        (progress: RagOperationProgressEvent): void => {
            setRunProgress(progress);
        },
        [],
    );

    const requestRagBuildStream = useCallback(
        async (
            signal: AbortSignal,
            {
                forceRebuild,
                resumeExisting = false,
            }: RagBuildStreamOptions,
        ): Promise<void> => {
            await runRagBuildStream(
                api,
                {
                    onLog: appendLog,
                    onStatus: handleRunStatus,
                    onError: handleRunError,
                    onProgress: handleRunProgress,
                },
                { signal, forceRebuild, resumeExisting },
            );
        },
        [api, appendLog, handleRunError, handleRunProgress, handleRunStatus],
    );

    const observeRagBuildStream = useCallback(
        async ({
            errorContext,
            markRunning = false,
            ...options
        }: ObserveRagBuildStreamOptions): Promise<void> => {
            runAbortControllerRef.current?.abort();
            const controller = new AbortController();
            runAbortControllerRef.current = controller;
            runLogCounterRef.current = 0;
            resetRunOutputStickToBottom();
            setRunLogs([]);
            setRunProgress(undefined);
            setRunError(undefined);
            setIsStopRequestPending(false);
            if (markRunning) {
                setIsBuildRunning(true);
            }

            try {
                await requestRagBuildStream(controller.signal, options);
            } catch (error) {
                if (!isAbortError(error)) {
                    setIsBuildRunning(false);
                    setIsStopRequestPending(false);
                    setRunError(handleFetchError(error, errorContext));
                }
            } finally {
                if (runAbortControllerRef.current === controller) {
                    runAbortControllerRef.current = undefined;
                }
            }
        },
        [requestRagBuildStream, resetRunOutputStickToBottom],
    );

    const handleRun = useCallback(
        async (forceRebuild = false): Promise<void> => {
            if (isOperationRunning) {
                return;
            }

            await observeRagBuildStream({
                errorContext: "Running KB builder",
                forceRebuild,
                markRunning: true,
            });
        },
        [isOperationRunning, observeRagBuildStream],
    );

    const handleRunClick = useCallback((): void => {
        void handleRun(false);
    }, [handleRun]);

    const handleRebuildClick = useCallback((): void => {
        void handleRun(true);
    }, [handleRun]);

    const handleStopBuildClick = useCallback((): void => {
        if (!isBuildRunning || isStopRequestPending) {
            return;
        }

        setIsStopRequestPending(true);
        setIsBuildRunning(true);
        void cancelRagBuild(api)
            .then((result) => {
                setIsBuildRunning(result.status === "cancelling");
            })
            .catch((error: unknown) => {
                if (isApiError(error) && error.status === 404) {
                    setIsBuildRunning(false);
                }
                setRunError(handleFetchError(error, "Stopping KB builder"));
            })
            .finally(() => {
                setIsStopRequestPending(false);
            });
    }, [api, isBuildRunning, isStopRequestPending]);

    const handleCopyEvalRagClick = useCallback(async (): Promise<void> => {
        if (isOperationRunning) {
            return;
        }

        runAbortControllerRef.current?.abort();
        const controller = new AbortController();
        runAbortControllerRef.current = controller;
        setIsCopyingEvalRag(true);
        runLogCounterRef.current = 0;
        resetRunOutputStickToBottom();
        setRunLogs([]);
        setRunProgress(undefined);
        setRunError(undefined);
        setIsBuildRunning(false);
        setIsStopRequestPending(false);

        try {
            await syncEvalRagStream(
                api,
                {
                    onLog: appendLog,
                    onStatus: (status) => {
                        setIsCopyingEvalRag(status.status === "start");
                    },
                    onError: handleRunError,
                    onProgress: handleRunProgress,
                },
                controller.signal,
            );
        } catch (error) {
            if (isAbortError(error)) {
                return;
            }
            const message = handleFetchError(error, "Syncing Eval KB");
            setRunError(message);
        } finally {
            if (runAbortControllerRef.current === controller) {
                runAbortControllerRef.current = undefined;
            }
            setIsCopyingEvalRag(false);
        }
    }, [
        api,
        appendLog,
        handleRunError,
        handleRunProgress,
        isOperationRunning,
        resetRunOutputStickToBottom,
    ]);

    useEffect(() => {
        runAbortControllerRef.current?.abort();
        const controller = new AbortController();
        runAbortControllerRef.current = controller;
        void requestRagBuildStream(controller.signal, { resumeExisting: true })
            .catch((error: unknown) => {
                if (!isAbortError(error)) {
                    setIsBuildRunning(false);
                    setIsStopRequestPending(false);
                    setRunError(handleFetchError(error, "Resuming KB builder"));
                }
            })
            .finally(() => {
                if (runAbortControllerRef.current === controller) {
                    runAbortControllerRef.current = undefined;
                }
            });

        return (): void => {
            runAbortControllerRef.current?.abort();
            runAbortControllerRef.current = undefined;
        };
    }, [requestRagBuildStream]);

    useEffect(() => {
        scrollRunOutputToBottomIfPinned();
    }, [runLogs, scrollRunOutputToBottomIfPinned]);

    const outputPane = (
        <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col gap-3">
            {runError !== undefined && <InlineError message={runError} />}
            <p className="text-muted-foreground text-xs">
                Live output is not replayed after reconnecting. Durable status and
                results remain available in KB Builder Jobs.
            </p>
            <div
                className="bg-muted/20 min-h-0 flex-1 overflow-auto rounded-md border p-4"
                onScroll={handleRunOutputScroll}
                ref={runOutputContainerRef}
            >
                <pre className="font-mono text-sm leading-relaxed break-words whitespace-pre-wrap">
                    {runLogs.map((entry) => (
                        <Fragment key={entry.id}>
                            {renderRichMarkup(entry.message)}
                            {"\n"}
                        </Fragment>
                    ))}
                    {isOperationRunning && (
                        <span className="bg-foreground ml-0.5 inline-block h-4 w-2 animate-pulse align-middle" />
                    )}
                </pre>
            </div>
        </div>
    );

    return (
        <PageShell
            className="min-h-0 overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="KB Builder">
                <Button
                    disabled={isOperationRunning}
                    onClick={handleRunClick}
                    type="button"
                    variant="outline"
                >
                    <Play data-icon="inline-start" />
                    Build KB
                </Button>
                <Button
                    disabled={isOperationRunning}
                    onClick={handleRebuildClick}
                    type="button"
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Rebuild KB
                </Button>
                <Button
                    disabled={
                        !isBuildRunning || isStopRequestPending || isCopyingEvalRag
                    }
                    onClick={handleStopBuildClick}
                    title="Request the running KB job to stop after its current step finishes."
                    type="button"
                    variant="outline"
                >
                    <StopCircle data-icon="inline-start" />
                    {isStopRequestPending ? "Stopping KB Job" : "Stop KB Job"}
                </Button>
                <Button
                    disabled={isOperationRunning}
                    onClick={() => {
                        void handleCopyEvalRagClick();
                    }}
                    type="button"
                    variant="outline"
                >
                    <Copy data-icon="inline-start" />
                    Sync Eval KB
                </Button>
            </PageHeader>

            {shouldShowWorkspace && (
                <PageSection className="flex min-h-0 flex-1">
                    {shouldShowSteps ? (
                        <ResizablePanelGroup
                            className="h-full min-h-0 min-w-0"
                            id="rag-builder-layout"
                            orientation="horizontal"
                            style={{ overflow: "visible" }}
                        >
                            <ResizablePanel
                                className="min-h-0 min-w-0"
                                defaultSize="50%"
                                id="rag-builder-steps-panel"
                                minSize="22%"
                                style={{ overflow: "visible" }}
                            >
                                <div className="h-full min-h-0 overflow-auto rounded-md border p-3">
                                    <ol className="flex flex-col gap-2">
                                        {runProgress.steps.map((step) => (
                                            <li
                                                className="flex items-center justify-between gap-3 rounded-md border p-3"
                                                key={step.key}
                                            >
                                                <span className="text-sm font-medium">
                                                    {step.label}
                                                </span>
                                                <Badge
                                                    variant={resolveStepStatusVariant(
                                                        step.status,
                                                    )}
                                                >
                                                    {resolveStepStatusLabel(
                                                        step.status,
                                                    )}
                                                </Badge>
                                            </li>
                                        ))}
                                    </ol>
                                </div>
                            </ResizablePanel>
                            <ResizableHandle
                                className="mx-2 aria-[orientation=horizontal]:mx-0 aria-[orientation=horizontal]:my-2"
                                withHandle
                            />
                            <ResizablePanel
                                className="min-h-0 min-w-0"
                                defaultSize="50%"
                                id="rag-builder-output-panel"
                                minSize="22%"
                                style={{ overflow: "visible" }}
                            >
                                {outputPane}
                            </ResizablePanel>
                        </ResizablePanelGroup>
                    ) : (
                        outputPane
                    )}
                </PageSection>
            )}
        </PageShell>
    );
};
