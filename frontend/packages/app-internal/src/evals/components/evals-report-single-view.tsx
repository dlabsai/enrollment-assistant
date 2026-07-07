import type { JSX } from "react";

import { InlineError, LoadingState } from "../../components/page-state";
import {
    formatEvalAudience,
    formatOptionalNumber,
    formatTimestamp,
} from "../lib/report-utils";
import type { EvalReportDetail, EvalReportSummary } from "../types";
import { EvalsReportDetail as EvalsReportDetailView } from "./evals-report-detail";
import {
    type EvalsReportViewMode,
    EvalsReportViewModeToggle,
} from "./evals-report-view-mode-toggle";

interface EvalsReportSingleViewProps {
    detailError: string | undefined;
    detailLoading: boolean;
    onLoadReportDetail: (reportId: string) => Promise<void> | void;
    onViewModeChange: (viewMode: EvalsReportViewMode) => void;
    reportMeta: EvalReportDetail | EvalReportSummary | undefined;
    selectedReportDetail: EvalReportDetail | undefined;
    selectedReportId: string | undefined;
    viewMode: EvalsReportViewMode;
}

export const EvalsReportSingleView = ({
    detailError,
    detailLoading,
    onLoadReportDetail,
    onViewModeChange,
    reportMeta,
    selectedReportDetail,
    selectedReportId,
    viewMode,
}: EvalsReportSingleViewProps): JSX.Element => (
    <>
        <div className="flex shrink-0 flex-col gap-3 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                {reportMeta !== undefined && (
                    <p className="text-muted-foreground min-w-0 text-sm break-words">
                        {reportMeta.title}
                    </p>
                )}
                <div className="ml-auto flex flex-wrap items-center gap-2">
                    <EvalsReportViewModeToggle
                        onViewModeChange={onViewModeChange}
                        viewMode={viewMode}
                    />
                </div>
            </div>
            {reportMeta !== undefined && (
                <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                    <span>Generated {formatTimestamp(reportMeta.generatedAt)}</span>
                    <span className="text-muted-foreground">•</span>
                    {reportMeta.isInternal !== null && (
                        <>
                            <span>{formatEvalAudience(reportMeta.isInternal)}</span>
                            <span className="text-muted-foreground">•</span>
                        </>
                    )}
                    <span>Repeats {formatOptionalNumber(reportMeta.repeats)}</span>
                    <span className="text-muted-foreground">•</span>
                    <span>
                        Concurrency {formatOptionalNumber(reportMeta.concurrency)}
                    </span>
                    <span className="text-muted-foreground">•</span>
                    <span>{formatOptionalNumber(reportMeta.caseCount)} cases</span>
                    <span className="text-muted-foreground">•</span>
                    <span>{formatOptionalNumber(reportMeta.runCount)} runs</span>
                </div>
            )}
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
            {detailError !== undefined && selectedReportId !== undefined && (
                <InlineError
                    message={detailError}
                    onRetry={() => void onLoadReportDetail(selectedReportId)}
                />
            )}
            {selectedReportId === undefined ? (
                <div className="text-muted-foreground text-sm">
                    No report selected.
                </div>
            ) : detailLoading ||
              (selectedReportDetail === undefined && detailError === undefined) ? (
                <LoadingState className="min-h-40 text-sm" />
            ) : selectedReportDetail === undefined ? null : (
                <EvalsReportDetailView report={selectedReportDetail} />
            )}
        </div>
    </>
);
