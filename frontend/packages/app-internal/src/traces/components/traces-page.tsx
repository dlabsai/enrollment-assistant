import { useNavigate, useSearch } from "@tanstack/react-router";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from "@va/shared/components/ui/sheet";
import { Switch } from "@va/shared/components/ui/switch";
import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { cn } from "@va/shared/lib/utils";
import {
    ChevronLeft,
    ChevronRight,
    ExternalLink,
    Filter,
    Maximize2,
    Minimize2,
    RefreshCw,
} from "lucide-react";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";

import { getDefaultDataTablePageSize } from "../../components/data-table-constants";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError } from "../../components/page-state";
import { TimeRangeFilter } from "../../components/time-range-filter";
import { formatLocaleNumber } from "../../lib/number-format";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    isTimeRangeValue,
    type TimeRangeValue,
} from "../../lib/time-range";
import { useTraceDetail } from "../hooks/use-trace-detail";
import { useTraceIndex } from "../hooks/use-trace-index";
import {
    formatDurationMs,
    formatPlatform,
    formatTimestamp,
} from "../lib/trace-utils";
import type { TracePlatformFilter } from "../types";
import { TraceDetailPanel } from "./trace-detail-panel";
import { TraceTable } from "./trace-table";

const platformOptions = [
    { label: "All platforms", value: "both" },
    { label: "Internal", value: "internal" },
    { label: "Public", value: "public" },
] as const;

const SHOW_PLATFORM_FILTER = false;

const runtimeTraceFilterStorageKey = "internal-traces-filters";
const evalTraceFilterStorageKey = "internal-eval-traces-filters";

type PlatformFilter = (typeof platformOptions)[number]["value"];

interface StoredTraceFilters {
    platform?: PlatformFilter;
    timeRange?: TimeRangeValue;
    customRange?: {
        start?: string;
        end?: string;
    };
}

const isPlatformFilter = (value: string): value is PlatformFilter =>
    platformOptions.some((option) => option.value === value);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

const parseStoredDate = (value?: string): Date | undefined => {
    if (value === undefined || value === "") {
        return undefined;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
};

const parseStoredCustomRange = (
    range?: StoredTraceFilters["customRange"],
): CustomTimeRange => ({
    start: parseStoredDate(range?.start),
    end: parseStoredDate(range?.end),
});

const parseStoredTraceFilters = (
    value: string,
): StoredTraceFilters | undefined => {
    try {
        const parsed: unknown = JSON.parse(value);
        if (!isRecord(parsed)) {
            return undefined;
        }
        const customRangeValue = isRecord(parsed.customRange)
            ? parsed.customRange
            : undefined;
        const platformValue =
            typeof parsed.platform === "string" &&
            isPlatformFilter(parsed.platform)
                ? parsed.platform
                : undefined;
        const timeRangeValue =
            typeof parsed.timeRange === "string" &&
            isTimeRangeValue(parsed.timeRange)
                ? parsed.timeRange
                : undefined;
        return {
            platform: platformValue,
            timeRange: timeRangeValue,
            customRange: {
                start:
                    typeof customRangeValue?.start === "string"
                        ? customRangeValue.start
                        : undefined,
                end:
                    typeof customRangeValue?.end === "string"
                        ? customRangeValue.end
                        : undefined,
            },
        };
    } catch {
        return undefined;
    }
};

const getStoredTraceFilters = (
    storageKey: string,
): StoredTraceFilters | undefined => {
    if (typeof window === "undefined") {
        return undefined;
    }
    const stored = window.localStorage.getItem(storageKey);
    if (stored === null || stored === "") {
        return undefined;
    }
    return parseStoredTraceFilters(stored);
};

const formatTraceId = (traceId: string): string => traceId;

type TraceSource = "runtime" | "evals";

interface TracesPageProps {
    source?: TraceSource;
}

export const TracesPage = ({
    source = "runtime",
}: TracesPageProps): JSX.Element => {
    const isEvalTraces = source === "evals";
    const routePath = isEvalTraces ? "/eval-traces" : "/traces";
    const aiOnlyStorageKey = isEvalTraces
        ? "internal-eval-traces-ai-only"
        : "internal-traces-ai-only";
    const traceFilterStorageKey = isEvalTraces
        ? evalTraceFilterStorageKey
        : runtimeTraceFilterStorageKey;
    const [aiOnly, setAiOnly] = useState(() => {
        if (typeof window === "undefined") {
            return true;
        }
        const stored = window.localStorage.getItem(aiOnlyStorageKey);
        return stored === null ? true : stored === "true";
    });
    const storedFilters = useMemo(
        () => getStoredTraceFilters(traceFilterStorageKey),
        [traceFilterStorageKey],
    );
    const [pageIndex, setPageIndex] = useState(0);
    const [pageSize, setPageSize] = useState(getDefaultDataTablePageSize);
    const [selectedPlatform, setSelectedPlatform] = useState<PlatformFilter>(
        () => {
            if (!SHOW_PLATFORM_FILTER) {
                return "both";
            }
            const storedPlatform = storedFilters?.platform;
            if (storedPlatform !== undefined) {
                return storedPlatform;
            }
            return "both";
        },
    );
    const [timeRange, setTimeRange] = useState<TimeRangeValue>(() => {
        const storedTimeRange = storedFilters?.timeRange;
        if (storedTimeRange !== undefined) {
            return storedTimeRange;
        }
        return "30d";
    });
    const [customRange, setCustomRange] = useState<CustomTimeRange>(() =>
        parseStoredCustomRange(storedFilters?.customRange),
    );
    const [referenceDate, setReferenceDate] = useState(() => new Date());
    const [detailExpanded, setDetailExpanded] = useState(false);
    const search = useSearch({ strict: false });
    const navigate = useNavigate();

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        window.localStorage.setItem(
            aiOnlyStorageKey,
            aiOnly ? "true" : "false",
        );
    }, [aiOnly, aiOnlyStorageKey]);

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        const payload: StoredTraceFilters = {
            platform: selectedPlatform,
            timeRange,
            customRange: {
                start: customRange.start?.toISOString(),
                end: customRange.end?.toISOString(),
            },
        };
        window.localStorage.setItem(
            traceFilterStorageKey,
            JSON.stringify(payload),
        );
    }, [customRange, selectedPlatform, timeRange, traceFilterStorageKey]);

    const platformFilter = selectedPlatform as TracePlatformFilter;
    const timeRangeParams = useMemo(
        () => getTimeRangeQueryParams(timeRange, referenceDate, customRange),
        [customRange, referenceDate, timeRange],
    );

    const { traces, total, loading, error, refresh } = useTraceIndex(
        aiOnly,
        platformFilter,
        pageIndex,
        pageSize,
        timeRangeParams.start,
        timeRangeParams.end,
        source,
    );

    const activeTraceId = search.trace;
    const selectedTrace = useMemo(
        () =>
            traces.find((trace) => trace.trace_id === search.trace) ??
            undefined,
        [search.trace, traces],
    );
    const sheetOpen = search.trace !== undefined;

    const {
        detail,
        loading: detailLoading,
        error: detailError,
        refresh: refreshDetail,
    } = useTraceDetail(activeTraceId, source);

    const clearTraceSelection = useCallback((): void => {
        void navigate({
            replace: true,
            search: (prev) => ({
                ...prev,
                trace: undefined,
                span: undefined,
            }),
            to: routePath,
        });
    }, [navigate, routePath]);

    const handleSpanChange = useCallback(
        (spanId: string | undefined): void => {
            if (activeTraceId === undefined) {
                return;
            }
            void navigate({
                replace: false,
                search: (prev) => ({
                    ...prev,
                    span: spanId,
                    trace: activeTraceId,
                }),
                to: routePath,
            });
        },
        [activeTraceId, navigate, routePath],
    );

    const handleSpanSync = useCallback(
        (spanId: string | undefined): void => {
            if (activeTraceId === undefined) {
                return;
            }
            void navigate({
                replace: true,
                search: (prev) => ({
                    ...prev,
                    span: spanId,
                    trace: activeTraceId,
                }),
                to: routePath,
            });
        },
        [activeTraceId, navigate, routePath],
    );

    const detailTitle =
        activeTraceId !== undefined && activeTraceId !== ""
            ? `Trace ${formatTraceId(activeTraceId)}`
            : "Trace details";
    const detailDescription =
        selectedTrace === undefined ? (
            "Trace details"
        ) : (
            <span className="inline-flex flex-wrap items-center gap-2">
                <Badge
                    variant={
                        selectedTrace.is_public === true
                            ? "secondary"
                            : "outline"
                    }
                >
                    {formatPlatform(selectedTrace.is_public)}
                </Badge>
                <span>{formatTimestamp(selectedTrace.started_at)}</span>
                <span>{formatDurationMs(selectedTrace.duration_ms)}</span>
                <span>
                    {formatLocaleNumber(selectedTrace.span_count)} spans
                </span>
            </span>
        );

    const selectedIndex =
        activeTraceId !== undefined && activeTraceId !== ""
            ? traces.findIndex((trace) => trace.trace_id === activeTraceId)
            : -1;
    const canGoPrev = selectedIndex > 0;
    const canGoNext = selectedIndex >= 0 && selectedIndex < traces.length - 1;

    const openTraceInNewTab = useCallback(() => {
        if (activeTraceId === undefined || activeTraceId === "") {
            return;
        }
        const base = `${window.location.origin}${window.location.pathname}`;
        const spanParam =
            search.span !== undefined && search.span !== ""
                ? `?span=${encodeURIComponent(search.span)}`
                : "";
        const url = `${base}#${routePath}/${activeTraceId}${spanParam}`;
        window.open(url, "_blank", "noopener,noreferrer");
    }, [activeTraceId, routePath, search.span]);

    return (
        <PageShell
            className="overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title={isEvalTraces ? "Eval Traces" : "Traces"}>
                {SHOW_PLATFORM_FILTER && (
                    <PageHeaderGroup>
                        <ToggleGroup
                            aria-label="Platform"
                            onValueChange={(value) => {
                                const [nextValue] = value;
                                const next = isPlatformFilter(nextValue)
                                    ? nextValue
                                    : "both";
                                setSelectedPlatform(next);
                                setPageIndex(0);
                                clearTraceSelection();
                            }}
                            value={[selectedPlatform]}
                            variant="outline"
                        >
                            {platformOptions.map((option) => (
                                <ToggleGroupItem
                                    key={option.value}
                                    value={option.value}
                                >
                                    {option.label}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                    </PageHeaderGroup>
                )}
                <PageHeaderGroup>
                    <TimeRangeFilter
                        customRange={customRange}
                        onChange={(value) => {
                            setTimeRange(value);
                            setReferenceDate(new Date());
                            setPageIndex(0);
                            clearTraceSelection();
                        }}
                        onCustomRangeChange={(value) => {
                            setCustomRange(value);
                            setReferenceDate(new Date());
                            setPageIndex(0);
                            clearTraceSelection();
                        }}
                        value={timeRange}
                    />
                </PageHeaderGroup>
                <PageHeaderGroup>
                    <Switch
                        checked={aiOnly}
                        onCheckedChange={(checked) => {
                            setAiOnly(checked);
                            setPageIndex(0);
                            clearTraceSelection();
                        }}
                    />
                    <span className="text-muted-foreground">AI only</span>
                </PageHeaderGroup>
                <Button
                    onClick={() => {
                        setSelectedPlatform("both");
                        setTimeRange("30d");
                        setCustomRange({});
                        setReferenceDate(new Date());
                        setAiOnly(true);
                        setPageIndex(0);
                        clearTraceSelection();
                    }}
                    variant="outline"
                >
                    <Filter data-icon="inline-start" />
                    Clear
                </Button>
                <Button
                    onClick={() => void refresh()}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            <PageSection className="flex min-h-0 flex-1 flex-col">
                {error !== undefined && <InlineError message={error} />}

                <TraceTable
                    isLoading={loading}
                    onPaginationChange={(updater) => {
                        const next =
                            typeof updater === "function"
                                ? updater({ pageIndex, pageSize })
                                : updater;
                        setPageIndex(next.pageIndex);
                        setPageSize(next.pageSize);
                        clearTraceSelection();
                    }}
                    onSelect={(trace) => {
                        void navigate({
                            search: (prev) => ({
                                ...prev,
                                trace: trace.trace_id,
                                span: undefined,
                            }),
                            to: routePath,
                        });
                    }}
                    pageCount={Math.max(1, Math.ceil(total / pageSize))}
                    pagination={{ pageIndex, pageSize }}
                    rowCount={total}
                    selectedTraceId={activeTraceId}
                    showPlatformColumn={SHOW_PLATFORM_FILTER}
                    traces={traces}
                />
            </PageSection>

            <Sheet
                onOpenChange={(open) => {
                    if (!open) {
                        clearTraceSelection();
                    }
                }}
                open={sheetOpen}
            >
                <SheetContent
                    className={cn(
                        "flex flex-col gap-4 p-0",
                        detailExpanded
                            ? "!w-screen !max-w-none"
                            : "!w-[min(100vw,860px)] !max-w-[min(100vw,860px)]",
                    )}
                    initialFocus={false}
                >
                    <SheetHeader className="border-b px-4 py-4">
                        <div className="flex items-start justify-between gap-4">
                            <SheetTitle>{detailTitle}</SheetTitle>
                            <TooltipProvider>
                                <div className="mr-8 flex items-center gap-2">
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    aria-label="Refresh trace"
                                                    onClick={() =>
                                                        void refreshDetail()
                                                    }
                                                    size="icon-sm"
                                                    variant="outline"
                                                >
                                                    <RefreshCw />
                                                </Button>
                                            }
                                        />
                                        <TooltipContent>
                                            Refresh Trace
                                        </TooltipContent>
                                    </Tooltip>
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    aria-label={
                                                        detailExpanded
                                                            ? "Collapse trace sheet"
                                                            : "Expand trace sheet"
                                                    }
                                                    onClick={() => {
                                                        setDetailExpanded(
                                                            (expanded) =>
                                                                !expanded,
                                                        );
                                                    }}
                                                    size="icon-sm"
                                                    variant="outline"
                                                >
                                                    {detailExpanded ? (
                                                        <Minimize2 />
                                                    ) : (
                                                        <Maximize2 />
                                                    )}
                                                </Button>
                                            }
                                        />
                                        <TooltipContent>
                                            {detailExpanded
                                                ? "Collapse sheet"
                                                : "Expand to full viewport"}
                                        </TooltipContent>
                                    </Tooltip>
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    aria-label="Open trace in new tab"
                                                    disabled={
                                                        activeTraceId ===
                                                            undefined ||
                                                        activeTraceId === ""
                                                    }
                                                    onClick={openTraceInNewTab}
                                                    size="icon-sm"
                                                    variant="outline"
                                                >
                                                    <ExternalLink />
                                                </Button>
                                            }
                                        />
                                        <TooltipContent>
                                            Open in new tab
                                        </TooltipContent>
                                    </Tooltip>
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    aria-label="Previous trace"
                                                    disabled={!canGoPrev}
                                                    onClick={() => {
                                                        if (!canGoPrev) {
                                                            return;
                                                        }
                                                        const previous =
                                                            traces[
                                                                selectedIndex -
                                                                    1
                                                            ];
                                                        void navigate({
                                                            search: (prev) => ({
                                                                ...prev,
                                                                trace: previous.trace_id,
                                                                span: undefined,
                                                            }),
                                                            to: routePath,
                                                        });
                                                    }}
                                                    size="icon-sm"
                                                    variant="outline"
                                                >
                                                    <ChevronLeft />
                                                </Button>
                                            }
                                        />
                                        <TooltipContent>
                                            Previous Trace
                                        </TooltipContent>
                                    </Tooltip>
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    aria-label="Next trace"
                                                    disabled={!canGoNext}
                                                    onClick={() => {
                                                        if (!canGoNext) {
                                                            return;
                                                        }
                                                        const next =
                                                            traces[
                                                                selectedIndex +
                                                                    1
                                                            ];
                                                        void navigate({
                                                            search: (prev) => ({
                                                                ...prev,
                                                                trace: next.trace_id,
                                                                span: undefined,
                                                            }),
                                                            to: routePath,
                                                        });
                                                    }}
                                                    size="icon-sm"
                                                    variant="outline"
                                                >
                                                    <ChevronRight />
                                                </Button>
                                            }
                                        />
                                        <TooltipContent>
                                            Next Trace
                                        </TooltipContent>
                                    </Tooltip>
                                </div>
                            </TooltipProvider>
                        </div>
                        <SheetDescription>{detailDescription}</SheetDescription>
                    </SheetHeader>

                    <div className="min-h-0 flex-1 overflow-hidden">
                        <TraceDetailPanel
                            detail={detail}
                            error={detailError}
                            loading={detailLoading}
                            onSpanChange={handleSpanChange}
                            onSpanSync={handleSpanSync}
                            selectedSpanId={search.span}
                        />
                    </div>
                </SheetContent>
            </Sheet>
        </PageShell>
    );
};
