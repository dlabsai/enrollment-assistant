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
    type Dispatch,
    type JSX,
    type SetStateAction,
    useEffect,
    useMemo,
} from "react";

import {
    buildModelRoleMap,
    formatDurationValue,
    formatModelValue,
    formatPercentValue,
    formatTimestamp,
} from "../lib/report-utils";
import type { EvalReportSummary } from "../types";
import {
    type EvalsReportViewMode,
    EvalsReportViewModeToggle,
} from "./evals-report-view-mode-toggle";

interface EvalsReportModelsViewProps {
    compareGroupReports: EvalReportSummary[];
    compareType: string | undefined;
    compareTypeOptions: string[];
    modelGroupKey: string | undefined;
    onCompareTypeChange: (type: string) => void;
    onModelGroupKeyChange: Dispatch<SetStateAction<string | undefined>>;
    onSelectReport: (reportId: string) => void;
    onViewModeChange: (viewMode: EvalsReportViewMode) => void;
    viewMode: EvalsReportViewMode;
}

interface ModelGroupReportMetrics {
    reportId: string;
    passRate: number | undefined;
    duration: number | undefined;
}

interface ModelGroupEntry {
    key: string;
    label: string;
    reports: EvalReportSummary[];
    metrics: ModelGroupReportMetrics[];
    passRateMedian: number | undefined;
    durationMedian: number | undefined;
    latestAt: number | undefined;
}

type ModelRole = "chatbot" | "guardrails";

type ModelRoleSet = readonly ModelRole[];

const buildModelComboKey = (
    roleMap: Partial<Record<ModelRole, string>>,
    roles: ModelRoleSet,
): string =>
    roles.map((role) => `${role}:${roleMap[role] ?? "unknown"}`).join("||");

const buildModelComboLabel = (
    roleMap: Partial<Record<ModelRole, string>>,
    roles: ModelRoleSet,
): string => {
    const labelMap: Record<ModelRole, string> = {
        chatbot: "Chatbot",
        guardrails: "Guardrails",
    };

    return roles
        .map((role) => `${labelMap[role]}: ${formatModelValue(roleMap[role])}`)
        .join(" | ");
};

const resolveModelRolesForType = (
    reportType: string | undefined,
): ModelRoleSet =>
    reportType?.toLowerCase().includes("guardrail") === true
        ? ["guardrails"]
        : ["guardrails", "chatbot"];

const median = (values: number[]): number | undefined => {
    if (values.length === 0) {
        return undefined;
    }
    const sorted = [...values].toSorted((left, right) => left - right);
    const midpoint = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 1) {
        return sorted[midpoint];
    }
    const lower = sorted[midpoint - 1];
    const upper = sorted[midpoint];
    if (lower === undefined || upper === undefined) {
        return undefined;
    }
    return (lower + upper) / 2;
};

export const EvalsReportModelsView = ({
    compareGroupReports,
    compareType,
    compareTypeOptions,
    modelGroupKey,
    onCompareTypeChange,
    onModelGroupKeyChange,
    onSelectReport,
    onViewModeChange,
    viewMode,
}: EvalsReportModelsViewProps): JSX.Element => {
    const compareTypeSelectLabel = compareType ?? "Select type";

    const modelGroups = useMemo(() => {
        const groups = new Map<string, ModelGroupEntry>();
        const roles = resolveModelRolesForType(compareType);
        for (const report of compareGroupReports) {
            const roleMap = buildModelRoleMap(report);
            const key = buildModelComboKey(roleMap, roles);
            const label = buildModelComboLabel(roleMap, roles);
            const entry = groups.get(key) ?? {
                key,
                label,
                reports: [],
                metrics: [],
                passRateMedian: undefined,
                durationMedian: undefined,
                latestAt: undefined,
            };
            entry.reports.push(report);
            entry.metrics.push({
                reportId: report.id,
                passRate: report.passRateAverage,
                duration: report.durationMedianAverage,
            });
            const reportTime = new Date(report.generatedAt).getTime();
            entry.latestAt =
                entry.latestAt === undefined
                    ? reportTime
                    : Math.max(entry.latestAt, reportTime);
            groups.set(key, entry);
        }
        const entries = [...groups.values()].map((entry) => {
            const passRates = entry.metrics
                .map((metric) => metric.passRate)
                .filter((value): value is number => value !== undefined);
            const durations = entry.metrics
                .map((metric) => metric.duration)
                .filter((value): value is number => value !== undefined);
            return {
                ...entry,
                passRateMedian: median(passRates),
                durationMedian: median(durations),
            } satisfies ModelGroupEntry;
        });
        entries.sort((left, right) => {
            const leftTime = left.latestAt ?? 0;
            const rightTime = right.latestAt ?? 0;
            return rightTime - leftTime;
        });
        return entries;
    }, [compareGroupReports, compareType]);

    const resolvedModelGroupKey =
        modelGroupKey !== undefined &&
        modelGroups.some((entry) => entry.key === modelGroupKey)
            ? modelGroupKey
            : modelGroups[0]?.key;

    useEffect(() => {
        onModelGroupKeyChange((current) =>
            current !== undefined &&
            modelGroups.some((entry) => entry.key === current)
                ? current
                : modelGroups[0]?.key,
        );
    }, [modelGroups, onModelGroupKeyChange]);

    const selectedModelGroup =
        resolvedModelGroupKey === undefined
            ? undefined
            : modelGroups.find((entry) => entry.key === resolvedModelGroupKey);

    const selectedModelGroupMetrics = useMemo(() => {
        const metrics = new Map<string, ModelGroupReportMetrics>();
        if (selectedModelGroup !== undefined) {
            for (const entry of selectedModelGroup.metrics) {
                metrics.set(entry.reportId, entry);
            }
        }
        return metrics;
    }, [selectedModelGroup]);

    return (
        <>
            <div className="flex shrink-0 flex-col gap-3 pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-muted-foreground min-w-0 text-sm break-words">
                        {compareType ?? "Select a report type to view model groups."}
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
                        No eval reports are available to group yet.
                    </div>
                ) : (
                    <div className="flex flex-col gap-4">
                        <div className="grid gap-3 @lg/main:grid-cols-[1fr]">
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
                        </div>
                        <div className="flex flex-col gap-2">
                            <div className="text-foreground text-xs font-semibold">
                                Model groups
                            </div>
                            {modelGroups.length === 0 ? (
                                <div className="text-muted-foreground text-sm">
                                    No model group data available for the
                                    selected type.
                                </div>
                            ) : (
                                <div className="overflow-x-auto">
                                    <Table>
                                        <TableHeader>
                                            <TableRow>
                                                <TableHead>
                                                    Model combo
                                                </TableHead>
                                                <TableHead className="text-right">
                                                    Reports
                                                </TableHead>
                                                <TableHead className="text-right">
                                                    Median pass rate
                                                </TableHead>
                                                <TableHead className="text-right">
                                                    Median median duration
                                                </TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {modelGroups.map((entry) => {
                                                const isSelected =
                                                    entry.key ===
                                                    resolvedModelGroupKey;
                                                return (
                                                    <TableRow
                                                        className={`hover:bg-muted/50 cursor-pointer ${
                                                            isSelected
                                                                ? "bg-muted/50"
                                                                : ""
                                                        }`}
                                                        key={entry.key}
                                                        onClick={() => {
                                                            onModelGroupKeyChange(
                                                                entry.key,
                                                            );
                                                        }}
                                                    >
                                                        <TableCell className="text-xs break-words">
                                                            {entry.label}
                                                        </TableCell>
                                                        <TableCell className="text-right tabular-nums">
                                                            {entry.reports.length}
                                                        </TableCell>
                                                        <TableCell className="text-right tabular-nums">
                                                            {formatPercentValue(
                                                                entry.passRateMedian,
                                                            )}
                                                        </TableCell>
                                                        <TableCell className="text-right tabular-nums">
                                                            {formatDurationValue(
                                                                entry.durationMedian,
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
                        <div className="flex flex-col gap-2">
                            <div className="text-foreground text-xs font-semibold">
                                Reports
                            </div>
                            {selectedModelGroup === undefined ? (
                                <div className="text-muted-foreground text-sm">
                                    Select a model combo to view reports.
                                </div>
                            ) : selectedModelGroup.reports.length === 0 ? (
                                <div className="text-muted-foreground text-sm">
                                    No reports are available for the selected
                                    combo.
                                </div>
                            ) : (
                                <div className="overflow-x-auto">
                                    <Table>
                                        <TableHeader>
                                            <TableRow>
                                                <TableHead>Generated</TableHead>
                                                <TableHead>Report</TableHead>
                                                <TableHead className="text-right">
                                                    Pass rate
                                                </TableHead>
                                                <TableHead className="text-right">
                                                    Median duration
                                                </TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {selectedModelGroup.reports.map(
                                                (report) => {
                                                    const metrics =
                                                        selectedModelGroupMetrics.get(
                                                            report.id,
                                                        );
                                                    return (
                                                        <TableRow
                                                            className="hover:bg-muted/50 cursor-pointer"
                                                            key={report.id}
                                                            onClick={() => {
                                                                onSelectReport(
                                                                    report.id,
                                                                );
                                                                onViewModeChange(
                                                                    "report",
                                                                );
                                                            }}
                                                        >
                                                            <TableCell className="text-xs">
                                                                {formatTimestamp(
                                                                    report.generatedAt,
                                                                )}
                                                            </TableCell>
                                                            <TableCell className="text-xs break-words">
                                                                {report.title}
                                                            </TableCell>
                                                            <TableCell className="text-right tabular-nums">
                                                                {formatPercentValue(
                                                                    metrics?.passRate,
                                                                )}
                                                            </TableCell>
                                                            <TableCell className="text-right tabular-nums">
                                                                {formatDurationValue(
                                                                    metrics?.duration,
                                                                )}
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
                    </div>
                )}
            </div>
        </>
    );
};
