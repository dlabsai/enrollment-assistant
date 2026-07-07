import { useNavigate, useSearch } from "@tanstack/react-router";
import type {
    OnChangeFn,
    PaginationState,
    SortingState,
} from "@tanstack/react-table";
import { Button } from "@va/shared/components/ui/button";
import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
} from "@va/shared/components/ui/resizable";
import { isAbortError, isApiError } from "@va/shared/lib/api-client";
import { RefreshCw } from "lucide-react";
import {
    type JSX,
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { isDataTablePageSize } from "../../components/data-table-constants";
import { PageHeader } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError, PageError } from "../../components/page-state";
import { fetchEvalReport, fetchEvalReports } from "../lib/api";
import { sortReportsByGenerated } from "../lib/report-utils";
import {
    type EvalReportsSearch,
    isEvalReportsSortBy,
} from "../lib/reports-search-state";
import type { EvalReportDetail, EvalReportSummary } from "../types";
import { EvalsReportCompareView } from "./evals-report-compare-view";
import { EvalsReportModelsView } from "./evals-report-models-view";
import { EvalsReportSingleView } from "./evals-report-single-view";
import { EvalsReportTrendsView } from "./evals-report-trends-view";
import type { EvalsReportViewMode } from "./evals-report-view-mode-toggle";
import { EvalsReportsList } from "./evals-reports-list";

export const EvalsReportsPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const search = useSearch({ from: "/eval-reports" });
    const navigate = useNavigate({ from: "/eval-reports" });
    const {
        desc,
        page: currentPage,
        pageSize,
        query: searchValue,
        report: reportIdFromSearch,
        sortBy,
    } = search;
    const [reports, setReports] = useState<EvalReportSummary[]>([]);
    const [reportsTotal, setReportsTotal] = useState(0);
    const [reportOptions, setReportOptions] = useState<EvalReportSummary[]>(
        [],
    );
    const [loading, setLoading] = useState(true);
    const [hasLoaded, setHasLoaded] = useState(false);
    const [error, setError] = useState<string | undefined>();
    const [reportDetails, setReportDetails] = useState<
        Record<string, EvalReportDetail | undefined>
    >({});
    const [detailLoadingId, setDetailLoadingId] = useState<
        string | undefined
    >();
    const [detailError, setDetailError] = useState<string | undefined>();
    const [viewMode, setViewMode] =
        useState<EvalsReportViewMode>("report");
    const [compareType, setCompareType] = useState<string | undefined>();
    const [compareLeftId, setCompareLeftId] = useState<string | undefined>();
    const [compareRightId, setCompareRightId] = useState<string | undefined>();
    const [compareSelectedIds, setCompareSelectedIds] = useState<string[]>([]);
    const [compareReportsOpen, setCompareReportsOpen] = useState(false);
    const [compareReportsSearch, setCompareReportsSearch] = useState("");
    const [modelGroupKey, setModelGroupKey] = useState<string | undefined>();
    const reportsRequestIdRef = useRef(0);
    const reportsAbortControllerRef = useRef<AbortController | undefined>(
        undefined,
    );
    const reportSearchDebounceTimeoutRef = useRef<number | undefined>(
        undefined,
    );
    const reportDetailRequestGenerationRef = useRef(0);
    const reportDetailRequestsRef = useRef(new Map<string, number>());
    const [reportSearchInputState, setReportSearchInputState] = useState(
        () => ({
            syncedSearchValue: searchValue,
            value: searchValue,
        }),
    );
    const reportSearchInputValue =
        reportSearchInputState.syncedSearchValue === searchValue
            ? reportSearchInputState.value
            : searchValue;

    const navigateWithSearch = useCallback(
        (
            updater: (
                previous: EvalReportsSearch,
            ) => Partial<EvalReportsSearch>,
            options?: { replace?: boolean },
        ): void => {
            void navigate({
                replace: options?.replace,
                search: (previous) => ({
                    ...previous,
                    ...updater(previous),
                }),
                to: "/eval-reports",
            });
        },
        [navigate],
    );

    const loadReports = useCallback(async () => {
        const requestId = reportsRequestIdRef.current + 1;
        reportsRequestIdRef.current = requestId;
        reportsAbortControllerRef.current?.abort();
        const abortController = new AbortController();
        reportsAbortControllerRef.current = abortController;
        setLoading(true);
        setError(undefined);
        try {
            const response = await fetchEvalReports(api, {
                descending: desc,
                limit: pageSize,
                offset: (currentPage - 1) * pageSize,
                search: searchValue,
                signal: abortController.signal,
                sortBy,
            });
            if (reportsRequestIdRef.current !== requestId) {
                return;
            }
            setReports(response.items);
            setReportsTotal(response.total);
            setHasLoaded(true);
        } catch (error_) {
            if (
                reportsRequestIdRef.current !== requestId ||
                isAbortError(error_)
            ) {
                return;
            }
            setError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to load eval reports",
            );
        } finally {
            if (reportsAbortControllerRef.current === abortController) {
                reportsAbortControllerRef.current = undefined;
            }
            if (reportsRequestIdRef.current === requestId) {
                setLoading(false);
            }
        }
    }, [api, currentPage, desc, pageSize, searchValue, sortBy]);

    const loadReportOptions = useCallback(async () => {
        try {
            const response = await fetchEvalReports(api, {
                descending: true,
                limit: 200,
                offset: 0,
                search: "",
                sortBy: "generated_at",
            });
            setReportOptions(response.items);
        } catch {
            setReportOptions([]);
        }
    }, [api]);

    const loadReportDetail = useCallback(
        async (reportId: string) => {
            if (reportDetailRequestsRef.current.has(reportId)) {
                return;
            }

            const requestGeneration = reportDetailRequestGenerationRef.current;
            reportDetailRequestsRef.current.set(reportId, requestGeneration);
            setDetailLoadingId(reportId);
            setDetailError(undefined);
            try {
                const response = await fetchEvalReport(api, reportId);
                if (
                    reportDetailRequestGenerationRef.current !==
                    requestGeneration
                ) {
                    return;
                }
                setReportDetails((prev) => ({
                    ...prev,
                    [reportId]: response,
                }));
            } catch (error_) {
                if (
                    reportDetailRequestGenerationRef.current !==
                    requestGeneration
                ) {
                    return;
                }
                if (isApiError(error_) && error_.status === 404) {
                    navigateWithSearch(
                        (previous) =>
                            previous.report === reportId
                                ? { report: undefined }
                                : {},
                        { replace: true },
                    );
                    return;
                }
                setDetailError(
                    error_ instanceof Error
                        ? error_.message
                        : "Failed to load report",
                );
            } finally {
                if (
                    reportDetailRequestsRef.current.get(reportId) ===
                    requestGeneration
                ) {
                    reportDetailRequestsRef.current.delete(reportId);
                }
                if (
                    reportDetailRequestGenerationRef.current ===
                    requestGeneration
                ) {
                    setDetailLoadingId((current) =>
                        current === reportId ? undefined : current,
                    );
                }
            }
        },
        [api, navigateWithSearch],
    );

    const selectedReportId = reportIdFromSearch;

    const handleSelectReport = useCallback(
        (reportId: string | undefined): void => {
            navigateWithSearch(() => ({
                report: reportId,
            }));
        },
        [navigateWithSearch],
    );

    useEffect(() => {
        void loadReports();
    }, [loadReports]);

    useEffect(
        () => (): void => {
            reportsRequestIdRef.current += 1;
            reportsAbortControllerRef.current?.abort();
            if (reportSearchDebounceTimeoutRef.current !== undefined) {
                window.clearTimeout(reportSearchDebounceTimeoutRef.current);
            }
        },
        [],
    );

    useEffect(() => {
        if (reportSearchDebounceTimeoutRef.current !== undefined) {
            window.clearTimeout(reportSearchDebounceTimeoutRef.current);
            reportSearchDebounceTimeoutRef.current = undefined;
        }
    }, [searchValue]);

    useEffect(() => {
        void loadReportOptions();
    }, [loadReportOptions]);

    const sorting = useMemo<SortingState>(
        () => [{ desc, id: sortBy }],
        [desc, sortBy],
    );
    const pagination = useMemo<PaginationState>(
        () => ({ pageIndex: currentPage - 1, pageSize }),
        [currentPage, pageSize],
    );
    const pageCount = Math.max(1, Math.ceil(reportsTotal / pageSize));
    const onPaginationChange: OnChangeFn<PaginationState> = (updater) => {
        const next =
            typeof updater === "function" ? updater(pagination) : updater;
        const nextPageSize = isDataTablePageSize(next.pageSize)
            ? next.pageSize
            : pageSize;
        navigateWithSearch(() => ({
            page: next.pageIndex + 1,
            pageSize: nextPageSize,
        }));
    };
    const onSortingChange: OnChangeFn<SortingState> = (updater) => {
        const next = typeof updater === "function" ? updater(sorting) : updater;
        const [nextSort] = next;
        navigateWithSearch(() => ({
            desc: nextSort?.desc ?? false,
            page: 1,
            sortBy: isEvalReportsSortBy(nextSort?.id)
                ? nextSort.id
                : "generated_at",
        }));
    };

    const handleReportSearchInputChange = useCallback(
        (value: string): void => {
            setReportSearchInputState({
                syncedSearchValue: searchValue,
                value,
            });
            if (reportSearchDebounceTimeoutRef.current !== undefined) {
                window.clearTimeout(reportSearchDebounceTimeoutRef.current);
            }
            reportSearchDebounceTimeoutRef.current = window.setTimeout(() => {
                reportSearchDebounceTimeoutRef.current = undefined;
                if (value === searchValue) {
                    return;
                }
                navigateWithSearch(
                    () => ({
                        page: 1,
                        query: value,
                    }),
                    { replace: true },
                );
            }, 300);
        },
        [navigateWithSearch, searchValue],
    );

    useEffect(() => {
        if (loading || !hasLoaded) {
            return;
        }
        if (currentPage > pageCount) {
            navigateWithSearch(() => ({ page: pageCount }), { replace: true });
        }
    }, [currentPage, hasLoaded, loading, navigateWithSearch, pageCount]);

    const groupedCompareReports = useMemo(() => {
        const groups = new Map<string, EvalReportSummary[]>();
        for (const report of reportOptions) {
            const existing = groups.get(report.title);
            if (existing === undefined) {
                groups.set(report.title, [report]);
            } else {
                existing.push(report);
            }
        }
        for (const group of groups.values()) {
            group.sort(sortReportsByGenerated);
        }
        return groups;
    }, [reportOptions]);

    const compareTypeOptions = useMemo(() => {
        const entries = [...groupedCompareReports.entries()].map(
            ([name, items]) => ({
                name,
                latestAt: new Date(items[0].generatedAt).getTime(),
            }),
        );
        entries.sort((left, right) => right.latestAt - left.latestAt);
        return entries.map((entry) => entry.name);
    }, [groupedCompareReports]);

    const compareGroupReports = useMemo(() => {
        if (compareType === undefined) {
            return [];
        }
        return groupedCompareReports.get(compareType) ?? [];
    }, [compareType, groupedCompareReports]);

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (compareTypeOptions.length === 0) {
                setCompareType(undefined);
                return;
            }
            setCompareType((current) =>
                current !== undefined &&
                current !== "" &&
                compareTypeOptions.includes(current)
                    ? current
                    : compareTypeOptions[0],
            );
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [compareTypeOptions]);

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (compareGroupReports.length === 0) {
                setCompareLeftId(undefined);
                return;
            }
            setCompareLeftId((current) => {
                if (
                    current !== undefined &&
                    compareGroupReports.some((report) => report.id === current)
                ) {
                    return current;
                }
                return compareGroupReports[0].id;
            });
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [compareGroupReports]);

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (compareGroupReports.length <= 1) {
                setCompareRightId(undefined);
                return;
            }
            setCompareRightId((current) => {
                if (
                    current !== undefined &&
                    current !== compareLeftId &&
                    compareGroupReports.some((report) => report.id === current)
                ) {
                    return current;
                }
                const fallbackReport = compareGroupReports.find(
                    (report) => report.id !== compareLeftId,
                );
                return fallbackReport
                    ? fallbackReport.id
                    : compareGroupReports[0].id;
            });
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [compareGroupReports, compareLeftId]);

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (compareGroupReports.length === 0) {
                setCompareSelectedIds([]);
                return;
            }
            setCompareSelectedIds((current) => {
                const filtered = current.filter((id) =>
                    compareGroupReports.some((report) => report.id === id),
                );
                if (filtered.length > 0) {
                    return filtered;
                }
                return compareGroupReports
                    .slice(0, Math.min(5, compareGroupReports.length))
                    .map((report) => report.id);
            });
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [compareGroupReports]);

    useEffect(() => {
        const ids = new Set<string>();
        if (viewMode === "report" && selectedReportId !== undefined) {
            ids.add(selectedReportId);
        }
        if (viewMode === "compare") {
            if (compareLeftId !== undefined) {
                ids.add(compareLeftId);
            }
            if (compareRightId !== undefined) {
                ids.add(compareRightId);
            }
        }
        for (const reportId of ids) {
            if (reportDetails[reportId] === undefined) {
                void loadReportDetail(reportId);
            }
        }
    }, [
        compareLeftId,
        compareRightId,
        loadReportDetail,
        reportDetails,
        selectedReportId,
        viewMode,
    ]);

    useEffect(() => {
        const timeout = setTimeout(() => {
            setDetailError(undefined);
        }, 0);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [compareLeftId, compareRightId, selectedReportId, viewMode]);

    const selectedReportDetail =
        selectedReportId === undefined
            ? undefined
            : reportDetails[selectedReportId];
    const selectedReportSummary = useMemo(
        () =>
            selectedReportId === undefined
                ? undefined
                : (reports.find((report) => report.id === selectedReportId) ??
                  reportOptions.find(
                      (report) => report.id === selectedReportId,
                  ) ??
                  selectedReportDetail),
        [reportOptions, reports, selectedReportDetail, selectedReportId],
    );
    const detailLoading =
        selectedReportId !== undefined &&
        detailLoadingId === selectedReportId &&
        selectedReportDetail === undefined;
    const reportMeta = selectedReportDetail ?? selectedReportSummary;

    const compareLeftSummary = useMemo(
        () =>
            compareLeftId === undefined
                ? undefined
                : reportOptions.find((report) => report.id === compareLeftId),
        [compareLeftId, reportOptions],
    );
    const compareRightSummary = useMemo(
        () =>
            compareRightId === undefined
                ? undefined
                : reportOptions.find((report) => report.id === compareRightId),
        [compareRightId, reportOptions],
    );
    const compareLeftDetail =
        compareLeftId === undefined ? undefined : reportDetails[compareLeftId];
    const compareRightDetail =
        compareRightId === undefined
            ? undefined
            : reportDetails[compareRightId];
    const compareLeftMeta = compareLeftDetail ?? compareLeftSummary;
    const compareRightMeta = compareRightDetail ?? compareRightSummary;

    const canSwapCompare =
        compareLeftId !== undefined && compareRightId !== undefined;

    const handleSwapCompare = useCallback(() => {
        if (!canSwapCompare) {
            return;
        }
        setCompareLeftId(compareRightId);
        setCompareRightId(compareLeftId);
    }, [canSwapCompare, compareLeftId, compareRightId]);

    const toggleCompareReport = useCallback((reportId: string): void => {
        setCompareSelectedIds((current) =>
            current.includes(reportId)
                ? current.filter((id) => id !== reportId)
                : [...current, reportId],
        );
    }, []);

    const handleSelectAllCompareReports = useCallback(() => {
        setCompareSelectedIds(compareGroupReports.map((report) => report.id));
    }, [compareGroupReports]);

    const handleClearCompareReports = useCallback(() => {
        setCompareSelectedIds([]);
    }, []);

    if (error !== undefined && !hasLoaded) {
        return <PageError message={error} onRetry={() => void loadReports()} />;
    }

    return (
        <PageShell
            className="min-h-0 overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="Eval Reports">
                <Button
                    onClick={() => {
                        reportDetailRequestGenerationRef.current += 1;
                        reportDetailRequestsRef.current.clear();
                        setDetailLoadingId(undefined);
                        setDetailError(undefined);
                        setReportDetails({});
                        void loadReports();
                        void loadReportOptions();
                    }}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            {error !== undefined && hasLoaded && (
                <PageSection>
                    <InlineError
                        message={error}
                        onRetry={() => void loadReports()}
                    />
                </PageSection>
            )}

            <PageSection className="flex min-h-0 flex-1">
                <ResizablePanelGroup
                    className="h-full min-h-0 min-w-0"
                    id="eval-reports-layout"
                    orientation="horizontal"
                    style={{ overflow: "visible" }}
                >
                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        defaultSize="50%"
                        id="eval-reports-list-panel"
                        minSize="22%"
                        style={{ overflow: "visible" }}
                    >
                        <EvalsReportsList
                            loading={loading}
                            onPaginationChange={onPaginationChange}
                            onSearchChange={handleReportSearchInputChange}
                            onSelectReport={handleSelectReport}
                            onSortingChange={onSortingChange}
                            pageCount={pageCount}
                            pagination={pagination}
                            reports={reports}
                            rowCount={reportsTotal}
                            searchInputValue={reportSearchInputValue}
                            selectedReportId={selectedReportId}
                            sorting={sorting}
                        />
                    </ResizablePanel>
                    <ResizableHandle
                        className="mx-2 aria-[orientation=horizontal]:mx-0 aria-[orientation=horizontal]:my-2"
                        withHandle
                    />
                    <ResizablePanel
                        className="min-h-0 min-w-0"
                        defaultSize="50%"
                        id="eval-reports-detail-panel"
                        minSize="22%"
                        style={{ overflow: "visible" }}
                    >
                        <section className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
                            {viewMode === "report" ? (
                                <EvalsReportSingleView
                                    detailError={detailError}
                                    detailLoading={detailLoading}
                                    onLoadReportDetail={loadReportDetail}
                                    onViewModeChange={setViewMode}
                                    reportMeta={reportMeta}
                                    selectedReportDetail={selectedReportDetail}
                                    selectedReportId={selectedReportId}
                                    viewMode={viewMode}
                                />
                            ) : viewMode === "compare" ? (
                                <EvalsReportCompareView
                                    canSwapCompare={canSwapCompare}
                                    compareGroupReports={compareGroupReports}
                                    compareLeftDetail={compareLeftDetail}
                                    compareLeftId={compareLeftId}
                                    compareLeftMeta={compareLeftMeta}
                                    compareRightDetail={compareRightDetail}
                                    compareRightId={compareRightId}
                                    compareRightMeta={compareRightMeta}
                                    compareType={compareType}
                                    compareTypeOptions={compareTypeOptions}
                                    detailError={detailError}
                                    onCompareLeftIdChange={setCompareLeftId}
                                    onCompareRightIdChange={setCompareRightId}
                                    onCompareTypeChange={setCompareType}
                                    onLoadReportDetail={loadReportDetail}
                                    onSwapCompare={handleSwapCompare}
                                    onViewModeChange={setViewMode}
                                    viewMode={viewMode}
                                />
                            ) : viewMode === "trends" ? (
                                <EvalsReportTrendsView
                                    compareGroupReports={compareGroupReports}
                                    compareReportsOpen={compareReportsOpen}
                                    compareReportsSearch={compareReportsSearch}
                                    compareSelectedIds={compareSelectedIds}
                                    compareType={compareType}
                                    compareTypeOptions={compareTypeOptions}
                                    onClearCompareReports={
                                        handleClearCompareReports
                                    }
                                    onCompareReportsOpenChange={
                                        setCompareReportsOpen
                                    }
                                    onCompareReportsSearchChange={
                                        setCompareReportsSearch
                                    }
                                    onCompareTypeChange={setCompareType}
                                    onSelectAllCompareReports={
                                        handleSelectAllCompareReports
                                    }
                                    onToggleCompareReport={toggleCompareReport}
                                    onViewModeChange={setViewMode}
                                    viewMode={viewMode}
                                />
                            ) : (
                                <EvalsReportModelsView
                                    compareGroupReports={compareGroupReports}
                                    compareType={compareType}
                                    compareTypeOptions={compareTypeOptions}
                                    modelGroupKey={modelGroupKey}
                                    onCompareTypeChange={setCompareType}
                                    onModelGroupKeyChange={setModelGroupKey}
                                    onSelectReport={handleSelectReport}
                                    onViewModeChange={setViewMode}
                                    viewMode={viewMode}
                                />
                            )}
                        </section>
                    </ResizablePanel>
                </ResizablePanelGroup>
            </PageSection>
        </PageShell>
    );
};
