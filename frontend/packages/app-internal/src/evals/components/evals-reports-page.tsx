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
import { useAsyncData } from "../../lib/hooks/use-async-data";
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

interface EvalReportsData {
    reports: EvalReportSummary[];
    total: number;
}

interface CompareReportSelectionState {
    groupKey: string;
    reportIds: string[];
}

const initialEvalReportsData: EvalReportsData = {
    reports: [],
    total: 0,
};
const initialReportOptions: EvalReportSummary[] = [];

const getCompareGroupKey = (reports: EvalReportSummary[]): string =>
    JSON.stringify(reports.map((report) => report.id));

const getDefaultCompareReportIds = (
    reports: EvalReportSummary[],
): string[] =>
    reports.slice(0, 5).map((report) => report.id);

const resolveCompareReportIds = (
    state: CompareReportSelectionState,
    groupKey: string,
    reports: EvalReportSummary[],
): string[] => {
    if (state.groupKey === groupKey) {
        return state.reportIds;
    }
    const availableIds = new Set(reports.map((report) => report.id));
    const retainedIds = state.reportIds.filter((id) => availableIds.has(id));
    return retainedIds.length > 0
        ? retainedIds
        : getDefaultCompareReportIds(reports);
};

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
    const loadReports = useCallback(
        async (signal: AbortSignal): Promise<EvalReportsData> => {
            const response = await fetchEvalReports(api, {
                descending: desc,
                limit: pageSize,
                offset: (currentPage - 1) * pageSize,
                search: searchValue,
                signal,
                sortBy,
            });
            return { reports: response.items, total: response.total };
        },
        [api, currentPage, desc, pageSize, searchValue, sortBy],
    );
    const {
        data: { reports, total: reportsTotal },
        loading,
        hasSucceeded,
        error,
        refresh: refreshReports,
    } = useAsyncData({
        errorMessage: "Failed to load eval reports",
        initialData: initialEvalReportsData,
        load: loadReports,
    });
    const loadReportOptions = useCallback(
        async (signal: AbortSignal) => {
            const response = await fetchEvalReports(api, {
                descending: true,
                limit: 200,
                offset: 0,
                search: "",
                signal,
                sortBy: "generated_at",
            });
            return response.items;
        },
        [api],
    );
    const { data: reportOptions, refresh: refreshReportOptions } = useAsyncData(
        {
            clearDataOnError: true,
            errorMessage: "Failed to load report options",
            initialData: initialReportOptions,
            load: loadReportOptions,
        },
    );
    const [reportDetails, setReportDetails] = useState<
        Record<string, EvalReportDetail | undefined>
    >({});
    const [detailErrors, setDetailErrors] = useState<
        Record<string, string | undefined>
    >({});
    const [viewMode, setViewMode] = useState<EvalsReportViewMode>("report");
    const [compareTypeState, setCompareTypeState] =
        useState<string | undefined>();
    const [compareLeftIdState, setCompareLeftIdState] = useState<
        string | undefined
    >();
    const [compareRightIdState, setCompareRightIdState] = useState<
        string | undefined
    >();
    const [compareSelection, setCompareSelection] =
        useState<CompareReportSelectionState>({
            groupKey: "",
            reportIds: [],
        });
    const [compareReportsOpen, setCompareReportsOpen] = useState(false);
    const [compareReportsSearch, setCompareReportsSearch] = useState("");
    const [modelGroupKey, setModelGroupKey] = useState<string | undefined>();
    const reportSearchDebounceTimeoutRef = useRef<number | undefined>(
        undefined,
    );
    const reportDetailRequestsRef = useRef(new Map<string, AbortController>());
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

    const abortReportDetailRequests = useCallback((): void => {
        for (const controller of reportDetailRequestsRef.current.values()) {
            controller.abort();
        }
        reportDetailRequestsRef.current.clear();
    }, []);

    const requestReportDetail = useCallback(
        (reportId: string): void => {
            if (reportDetailRequestsRef.current.has(reportId)) {
                return;
            }

            const controller = new AbortController();
            reportDetailRequestsRef.current.set(reportId, controller);
            void fetchEvalReport(api, reportId, controller.signal)
                .then(
                    (response) => {
                        if (!controller.signal.aborted) {
                            setReportDetails((current) => ({
                                ...current,
                                [reportId]: response,
                            }));
                        }
                    },
                    (error: unknown) => {
                        if (controller.signal.aborted || isAbortError(error)) {
                            return;
                        }
                        setDetailErrors((current) => ({
                            ...current,
                            [reportId]:
                                error instanceof Error && error.message !== ""
                                    ? error.message
                                    : "Failed to load report",
                        }));
                        if (isApiError(error) && error.status === 404) {
                            navigateWithSearch(
                                (previous) =>
                                    previous.report === reportId
                                        ? { report: undefined }
                                        : {},
                                { replace: true },
                            );
                        }
                    },
                )
                .finally(() => {
                    if (
                        reportDetailRequestsRef.current.get(reportId) ===
                        controller
                    ) {
                        reportDetailRequestsRef.current.delete(reportId);
                    }
                });
        },
        [api, navigateWithSearch],
    );

    const retryReportDetail = useCallback(
        (reportId: string): void => {
            if (detailErrors[reportId] === undefined) {
                return;
            }
            setDetailErrors((current) => ({
                ...current,
                [reportId]: undefined,
            }));
            requestReportDetail(reportId);
        },
        [detailErrors, requestReportDetail],
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

    useEffect(
        () => (): void => {
            abortReportDetailRequests();
            if (reportSearchDebounceTimeoutRef.current !== undefined) {
                window.clearTimeout(reportSearchDebounceTimeoutRef.current);
            }
        },
        [abortReportDetailRequests],
    );

    useEffect(() => {
        if (reportSearchDebounceTimeoutRef.current !== undefined) {
            window.clearTimeout(reportSearchDebounceTimeoutRef.current);
            reportSearchDebounceTimeoutRef.current = undefined;
        }
    }, [searchValue]);

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
        if (loading || !hasSucceeded) {
            return;
        }
        if (currentPage > pageCount) {
            navigateWithSearch(() => ({ page: pageCount }), { replace: true });
        }
    }, [currentPage, hasSucceeded, loading, navigateWithSearch, pageCount]);

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

    const compareType =
        compareTypeState !== undefined &&
        compareTypeOptions.includes(compareTypeState)
            ? compareTypeState
            : compareTypeOptions[0];
    const compareGroupReports = useMemo(
        () =>
            compareType === undefined
                ? []
                : (groupedCompareReports.get(compareType) ?? []),
        [compareType, groupedCompareReports],
    );
    const compareGroupKey = useMemo(
        () => getCompareGroupKey(compareGroupReports),
        [compareGroupReports],
    );
    const compareLeftId =
        compareLeftIdState !== undefined &&
        compareGroupReports.some(
            (report) => report.id === compareLeftIdState,
        )
            ? compareLeftIdState
            : compareGroupReports[0]?.id;
    const compareRightId =
        compareRightIdState !== undefined &&
        compareRightIdState !== compareLeftId &&
        compareGroupReports.some(
            (report) => report.id === compareRightIdState,
        )
            ? compareRightIdState
            : compareGroupReports.find((report) => report.id !== compareLeftId)
                  ?.id;
    const compareSelectedIds = useMemo(
        () =>
            resolveCompareReportIds(
                compareSelection,
                compareGroupKey,
                compareGroupReports,
            ),
        [compareGroupKey, compareGroupReports, compareSelection],
    );

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
            if (
                reportDetails[reportId] === undefined &&
                detailErrors[reportId] === undefined
            ) {
                requestReportDetail(reportId);
            }
        }
    }, [
        compareLeftId,
        compareRightId,
        detailErrors,
        reportDetails,
        requestReportDetail,
        selectedReportId,
        viewMode,
    ]);

    const detailError =
        viewMode === "report"
            ? selectedReportId === undefined
                ? undefined
                : detailErrors[selectedReportId]
            : viewMode === "compare"
              ? ((compareLeftId === undefined
                    ? undefined
                    : detailErrors[compareLeftId]) ??
                (compareRightId === undefined
                    ? undefined
                    : detailErrors[compareRightId]))
              : undefined;

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
        selectedReportDetail === undefined &&
        detailError === undefined;
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
        setCompareLeftIdState(compareRightId);
        setCompareRightIdState(compareLeftId);
    }, [canSwapCompare, compareLeftId, compareRightId]);

    const toggleCompareReport = useCallback(
        (reportId: string): void => {
            setCompareSelection((current) => {
                const currentIds = resolveCompareReportIds(
                    current,
                    compareGroupKey,
                    compareGroupReports,
                );
                return {
                    groupKey: compareGroupKey,
                    reportIds: currentIds.includes(reportId)
                        ? currentIds.filter((id) => id !== reportId)
                        : [...currentIds, reportId],
                };
            });
        },
        [compareGroupKey, compareGroupReports],
    );

    const handleSelectAllCompareReports = useCallback(() => {
        setCompareSelection({
            groupKey: compareGroupKey,
            reportIds: compareGroupReports.map((report) => report.id),
        });
    }, [compareGroupKey, compareGroupReports]);

    const handleClearCompareReports = useCallback(() => {
        setCompareSelection({ groupKey: compareGroupKey, reportIds: [] });
    }, [compareGroupKey]);

    if (error !== undefined && !hasSucceeded) {
        return (
            <PageError
                message={error}
                onRetry={refreshReports}
            />
        );
    }

    return (
        <PageShell
            className="min-h-0 overflow-hidden"
            variant="dashboard"
        >
            <PageHeader title="Eval Reports">
                <Button
                    onClick={() => {
                        abortReportDetailRequests();
                        setDetailErrors({});
                        setReportDetails({});
                        refreshReports();
                        refreshReportOptions();
                    }}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
            </PageHeader>

            {error !== undefined && hasSucceeded && (
                <PageSection>
                    <InlineError
                        message={error}
                        onRetry={refreshReports}
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
                                    onRetryReportDetail={retryReportDetail}
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
                                    onCompareLeftIdChange={setCompareLeftIdState}
                                    onCompareRightIdChange={
                                        setCompareRightIdState
                                    }
                                    onCompareTypeChange={setCompareTypeState}
                                    onRetryReportDetail={retryReportDetail}
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
                                    onCompareTypeChange={setCompareTypeState}
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
                                    onCompareTypeChange={setCompareTypeState}
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
