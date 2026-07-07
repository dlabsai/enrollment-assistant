import { Button } from "@va/shared/components/ui/button";
import { Label } from "@va/shared/components/ui/label";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@va/shared/components/ui/table";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { ArrowLeftRight } from "lucide-react";
import { type JSX, useMemo } from "react";

import { InlineError, LoadingState } from "../../components/page-state";
import {
    buildCompareRows,
    buildModelCompareRows,
    formatDeltaDuration,
    formatDeltaPercent,
    formatDurationValue,
    formatEvalAudience,
    formatModelValue,
    formatPercentValue,
    formatReportMeta,
    formatTimestamp,
    getDeltaClassName,
    parseModelConfigurations,
    parseSummaryTable,
    resolveModelDelta,
} from "../lib/report-utils";
import type { EvalReportDetail, EvalReportSummary } from "../types";
import {
    type EvalsReportViewMode,
    EvalsReportViewModeToggle,
} from "./evals-report-view-mode-toggle";

interface EvalsReportCompareViewProps {
    canSwapCompare: boolean;
    compareGroupReports: EvalReportSummary[];
    compareLeftDetail: EvalReportDetail | undefined;
    compareLeftId: string | undefined;
    compareLeftMeta: EvalReportDetail | EvalReportSummary | undefined;
    compareRightDetail: EvalReportDetail | undefined;
    compareRightId: string | undefined;
    compareRightMeta: EvalReportDetail | EvalReportSummary | undefined;
    compareType: string | undefined;
    compareTypeOptions: string[];
    detailError: string | undefined;
    onCompareLeftIdChange: (reportId: string) => void;
    onCompareRightIdChange: (reportId: string) => void;
    onCompareTypeChange: (type: string) => void;
    onLoadReportDetail: (reportId: string) => Promise<void> | void;
    onSwapCompare: () => void;
    onViewModeChange: (viewMode: EvalsReportViewMode) => void;
    viewMode: EvalsReportViewMode;
}

const formatReportSelectLabel = (
    report: EvalReportSummary | EvalReportDetail | undefined,
): string | undefined => {
    if (report === undefined) {
        return undefined;
    }
    const parts = [formatTimestamp(report.generatedAt), report.title];
    if (report.isInternal !== null) {
        parts.push(formatEvalAudience(report.isInternal));
    }
    return parts.join(" · ");
};

export const EvalsReportCompareView = ({
    canSwapCompare,
    compareGroupReports,
    compareLeftDetail,
    compareLeftId,
    compareLeftMeta,
    compareRightDetail,
    compareRightId,
    compareRightMeta,
    compareType,
    compareTypeOptions,
    detailError,
    onCompareLeftIdChange,
    onCompareRightIdChange,
    onCompareTypeChange,
    onLoadReportDetail,
    onSwapCompare,
    onViewModeChange,
    viewMode,
}: EvalsReportCompareViewProps): JSX.Element => {
    const compareLeftSelectLabel = formatReportSelectLabel(compareLeftMeta);
    const compareRightSelectLabel = formatReportSelectLabel(compareRightMeta);
    const compareTypeSelectLabel = compareType ?? "Select type";
    const compareLoading =
        (compareLeftId !== undefined && compareLeftDetail === undefined) ||
        (compareRightId !== undefined && compareRightDetail === undefined);

    const compareRows = useMemo(() => {
        if (!compareLeftDetail || !compareRightDetail) {
            return [];
        }
        return buildCompareRows(
            parseSummaryTable(compareLeftDetail),
            parseSummaryTable(compareRightDetail),
        );
    }, [compareLeftDetail, compareRightDetail]);

    const compareModelRows = useMemo(() => {
        if (!compareLeftDetail || !compareRightDetail) {
            return [];
        }
        return buildModelCompareRows(
            parseModelConfigurations(compareLeftDetail),
            parseModelConfigurations(compareRightDetail),
        );
    }, [compareLeftDetail, compareRightDetail]);

    return (
        <>
            <div className="flex shrink-0 flex-col gap-3 pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-muted-foreground min-w-0 text-sm break-words">
                        {compareType ?? "Select a report type to compare."}
                    </p>
                    <EvalsReportViewModeToggle
                        onViewModeChange={onViewModeChange}
                        viewMode={viewMode}
                    />
                </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
                {compareTypeOptions.length === 0 ? (
                    <div className="text-muted-foreground text-sm">
                        No eval reports are available to compare yet.
                    </div>
                ) : (
                    <div className="flex flex-col gap-4">
                        <div className="grid gap-3 @lg/main:grid-cols-[1fr_1fr_auto_1fr]">
                            <div className="flex flex-col gap-1">
                                <Label className="text-muted-foreground text-xs">
                                    Type
                                </Label>
                                <Select
                                    onValueChange={(value) => {
                                        if (value === null) {
                                            return;
                                        }
                                        onCompareTypeChange(value);
                                    }}
                                    value={compareType}
                                >
                                    <SelectTrigger className="w-full">
                                        <SelectValue placeholder="Select type">
                                            {compareTypeSelectLabel}
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            {compareTypeOptions.map((type) => (
                                                <SelectItem
                                                    key={type}
                                                    value={type}
                                                >
                                                    {type}
                                                </SelectItem>
                                            ))}
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex flex-col gap-1">
                                <Label className="text-muted-foreground text-xs">
                                    Baseline
                                </Label>
                                <Select
                                    onValueChange={(value) => {
                                        if (value === null) {
                                            return;
                                        }
                                        onCompareLeftIdChange(value);
                                    }}
                                    value={compareLeftId}
                                >
                                    <SelectTrigger className="w-full">
                                        <SelectValue placeholder="Select report">
                                            {compareLeftSelectLabel}
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            {compareGroupReports.map((report) => (
                                                <SelectItem
                                                    key={report.id}
                                                    value={report.id}
                                                >
                                                    <span className="flex flex-col text-left">
                                                        <span>
                                                            {formatTimestamp(
                                                                report.generatedAt,
                                                            )}
                                                        </span>
                                                        <span className="text-muted-foreground text-xs">
                                                            {report.title}
                                                        </span>
                                                    </span>
                                                </SelectItem>
                                            ))}
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex flex-col gap-1">
                                <Label className="text-muted-foreground text-xs">
                                    Swap
                                </Label>
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                aria-label="Swap baseline and compare reports"
                                                disabled={!canSwapCompare}
                                                onClick={onSwapCompare}
                                                size="icon-sm"
                                                type="button"
                                                variant="outline"
                                            >
                                                <ArrowLeftRight />
                                            </Button>
                                        }
                                    />
                                    <TooltipContent side="top">
                                        Swap baseline and compare
                                    </TooltipContent>
                                </Tooltip>
                            </div>
                            <div className="flex flex-col gap-1">
                                <Label className="text-muted-foreground text-xs">
                                    Compare
                                </Label>
                                <Select
                                    disabled={compareGroupReports.length <= 1}
                                    onValueChange={(value) => {
                                        if (value === null) {
                                            return;
                                        }
                                        if (value === compareLeftId) {
                                            return;
                                        }
                                        onCompareRightIdChange(value);
                                    }}
                                    value={compareRightId}
                                >
                                    <SelectTrigger className="w-full">
                                        <SelectValue placeholder="Select report">
                                            {compareRightSelectLabel}
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            {compareGroupReports
                                                .filter(
                                                    (report) =>
                                                        report.id !==
                                                        compareLeftId,
                                                )
                                                .map((report) => (
                                                    <SelectItem
                                                        key={report.id}
                                                        value={report.id}
                                                    >
                                                        <span className="flex flex-col text-left">
                                                            <span>
                                                                {formatTimestamp(
                                                                    report.generatedAt,
                                                                )}
                                                            </span>
                                                            <span className="text-muted-foreground text-xs">
                                                                {report.title}
                                                            </span>
                                                        </span>
                                                    </SelectItem>
                                                ))}
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                        <div className="text-muted-foreground grid gap-3 text-xs @lg/main:grid-cols-2">
                            <div>
                                <div className="text-foreground text-xs font-semibold">
                                    Baseline
                                </div>
                                <div>
                                    {compareLeftMeta === undefined
                                        ? "Select a baseline report to compare."
                                        : formatReportMeta(compareLeftMeta)}
                                </div>
                            </div>
                            <div>
                                <div className="text-foreground text-xs font-semibold">
                                    Compare
                                </div>
                                <div>
                                    {compareRightMeta === undefined
                                        ? "Select a report to compare against the baseline."
                                        : formatReportMeta(compareRightMeta)}
                                </div>
                            </div>
                        </div>
                        {detailError === undefined ? compareGroupReports.length < 2 ? (
                            <div className="text-muted-foreground text-sm">
                                Select a report type with at least two runs to
                                compare.
                            </div>
                        ) : compareLeftId === undefined ||
                          compareRightId === undefined ? (
                            <div className="text-muted-foreground text-sm">
                                Select two reports to compare.
                            </div>
                        ) : compareLoading ? (
                            <LoadingState className="min-h-40 text-sm" />
                        ) : (
                            <div className="flex flex-col gap-6">
                                <div className="flex flex-col gap-2">
                                    <div className="text-foreground text-xs font-semibold">
                                        Models
                                    </div>
                                    {compareModelRows.length === 0 ? (
                                        <div className="text-muted-foreground text-sm">
                                            No model configuration data
                                            available.
                                        </div>
                                    ) : (
                                        <div className="overflow-x-auto">
                                            <Table>
                                                <TableHeader>
                                                    <TableRow>
                                                        <TableHead>
                                                            Role
                                                        </TableHead>
                                                        <TableHead>
                                                            Baseline
                                                        </TableHead>
                                                        <TableHead>
                                                            Compare
                                                        </TableHead>
                                                        <TableHead>Δ</TableHead>
                                                    </TableRow>
                                                </TableHeader>
                                                <TableBody>
                                                    {compareModelRows.map(
                                                        (row) => {
                                                            const leftModel =
                                                                row.left?.model;
                                                            const rightModel =
                                                                row.right?.model;
                                                            const delta =
                                                                resolveModelDelta(
                                                                    leftModel,
                                                                    rightModel,
                                                                );
                                                            return (
                                                                <TableRow
                                                                    key={
                                                                        row.role
                                                                    }
                                                                >
                                                                    <TableCell className="font-medium">
                                                                        {
                                                                            row.role
                                                                        }
                                                                    </TableCell>
                                                                    <TableCell className="text-xs break-words">
                                                                        {formatModelValue(
                                                                            leftModel,
                                                                        )}
                                                                    </TableCell>
                                                                    <TableCell className="text-xs break-words">
                                                                        {formatModelValue(
                                                                            rightModel,
                                                                        )}
                                                                    </TableCell>
                                                                    <TableCell
                                                                        className={`text-xs ${delta.className}`}
                                                                    >
                                                                        {
                                                                            delta.label
                                                                        }
                                                                    </TableCell>
                                                                </TableRow>
                                                            );
                                                        },
                                                    )}
                                                </TableBody>
                                            </Table>
                                        </div>
                                    )}
                                </div>
                                <div className="flex flex-col gap-2">
                                    <div className="text-foreground text-xs font-semibold">
                                        Summary
                                    </div>
                                    {compareRows.length === 0 ? (
                                        <div className="text-muted-foreground text-sm">
                                            No summary data available for
                                            comparison.
                                        </div>
                                    ) : (
                                        <div className="overflow-x-auto">
                                            <Table>
                                                <TableHeader>
                                                    <TableRow>
                                                        <TableHead>
                                                            Case
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Pass (Baseline)
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Pass (Compare)
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Δ
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Errors (Baseline)
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Errors (Compare)
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Δ
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Median (Baseline)
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Median (Compare)
                                                        </TableHead>
                                                        <TableHead className="text-right">
                                                            Δ
                                                        </TableHead>
                                                    </TableRow>
                                                </TableHeader>
                                                <TableBody>
                                                    {compareRows.map((row) => {
                                                        const {
                                                            caseName,
                                                            left,
                                                            right,
                                                        } = row;
                                                        const leftPassRate =
                                                            left?.passRate;
                                                        const rightPassRate =
                                                            right?.passRate;
                                                        const passDelta =
                                                            leftPassRate !==
                                                                undefined &&
                                                            rightPassRate !==
                                                                undefined
                                                                ? rightPassRate -
                                                                  leftPassRate
                                                                : undefined;
                                                        const leftErrorRate =
                                                            left?.runtimeErrorRate;
                                                        const rightErrorRate =
                                                            right?.runtimeErrorRate;
                                                        const errorDelta =
                                                            leftErrorRate !==
                                                                undefined &&
                                                            rightErrorRate !==
                                                                undefined
                                                                ? rightErrorRate -
                                                                  leftErrorRate
                                                                : undefined;
                                                        const leftDuration =
                                                            left?.durationMedian;
                                                        const rightDuration =
                                                            right?.durationMedian;
                                                        const durationDelta =
                                                            leftDuration !==
                                                                undefined &&
                                                            rightDuration !==
                                                                undefined
                                                                ? rightDuration -
                                                                  leftDuration
                                                                : undefined;
                                                        return (
                                                            <TableRow
                                                                key={caseName}
                                                            >
                                                                <TableCell className="font-medium">
                                                                    {caseName}
                                                                </TableCell>
                                                                <TableCell className="text-right tabular-nums">
                                                                    {formatPercentValue(
                                                                        leftPassRate,
                                                                    )}
                                                                </TableCell>
                                                                <TableCell className="text-right tabular-nums">
                                                                    {formatPercentValue(
                                                                        rightPassRate,
                                                                    )}
                                                                </TableCell>
                                                                <TableCell
                                                                    className={`text-right tabular-nums ${getDeltaClassName(
                                                                        passDelta,
                                                                        true,
                                                                    )}`}
                                                                >
                                                                    {formatDeltaPercent(
                                                                        passDelta,
                                                                    )}
                                                                </TableCell>
                                                                <TableCell className="text-right tabular-nums">
                                                                    {formatPercentValue(
                                                                        leftErrorRate,
                                                                    )}
                                                                </TableCell>
                                                                <TableCell className="text-right tabular-nums">
                                                                    {formatPercentValue(
                                                                        rightErrorRate,
                                                                    )}
                                                                </TableCell>
                                                                <TableCell
                                                                    className={`text-right tabular-nums ${getDeltaClassName(
                                                                        errorDelta,
                                                                        false,
                                                                    )}`}
                                                                >
                                                                    {formatDeltaPercent(
                                                                        errorDelta,
                                                                    )}
                                                                </TableCell>
                                                                <TableCell className="text-right tabular-nums">
                                                                    {formatDurationValue(
                                                                        leftDuration,
                                                                    )}
                                                                </TableCell>
                                                                <TableCell className="text-right tabular-nums">
                                                                    {formatDurationValue(
                                                                        rightDuration,
                                                                    )}
                                                                </TableCell>
                                                                <TableCell
                                                                    className={`text-right tabular-nums ${getDeltaClassName(
                                                                        durationDelta,
                                                                        false,
                                                                    )}`}
                                                                >
                                                                    {formatDeltaDuration(
                                                                        durationDelta,
                                                                    )}
                                                                </TableCell>
                                                            </TableRow>
                                                        );
                                                    })}
                                                </TableBody>
                                            </Table>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ) : (
                            <InlineError
                                message={detailError}
                                onRetry={() => {
                                    if (compareLeftId !== undefined) {
                                        void onLoadReportDetail(compareLeftId);
                                    }
                                    if (
                                        compareRightId !== undefined &&
                                        compareRightId !== compareLeftId
                                    ) {
                                        void onLoadReportDetail(compareRightId);
                                    }
                                }}
                            />
                        )}
                    </div>
                )}
            </div>
        </>
    );
};
