import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "@va/shared/components/ui/command";
import { Label } from "@va/shared/components/ui/label";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@va/shared/components/ui/popover";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { type JSX, useMemo } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
    type ChartConfig,
    ChartContainer,
    ChartTooltip,
} from "@/components/ui/chart";

import {
    buildModelRoleMap,
    formatDurationValue,
    formatModelValue,
    formatOptionalNumber,
    formatPercentValue,
    formatTimestamp,
} from "../lib/report-utils";
import type { EvalReportSummary } from "../types";
import {
    type EvalsReportViewMode,
    EvalsReportViewModeToggle,
} from "./evals-report-view-mode-toggle";

interface EvalsReportTrendsViewProps {
    compareGroupReports: EvalReportSummary[];
    compareReportsOpen: boolean;
    compareReportsSearch: string;
    compareSelectedIds: string[];
    compareType: string | undefined;
    compareTypeOptions: string[];
    onClearCompareReports: () => void;
    onCompareReportsOpenChange: (open: boolean) => void;
    onCompareReportsSearchChange: (value: string) => void;
    onCompareTypeChange: (type: string) => void;
    onSelectAllCompareReports: () => void;
    onToggleCompareReport: (reportId: string) => void;
    onViewModeChange: (viewMode: EvalsReportViewMode) => void;
    viewMode: EvalsReportViewMode;
}

interface CompareChartDatum {
    id: string;
    label: string;
    passRate: number | undefined;
    duration: number | undefined;
    chatbotModel?: string;
    guardrailsModel?: string;
}

const passRateChartConfig = {
    passRate: {
        label: "Pass rate",
        color: "var(--chart-2)",
    },
} satisfies ChartConfig;

const durationChartConfig = {
    duration: {
        label: "Median duration",
        color: "var(--chart-4)",
    },
} satisfies ChartConfig;

const CompareChartTooltip = ({
    active,
    payload,
    metric,
}: {
    active?: boolean;
    payload?: { value?: number | string; payload?: CompareChartDatum }[];
    metric: "passRate" | "duration";
}): JSX.Element | undefined => {
    if (active !== true || !payload || payload.length === 0) {
        return undefined;
    }
    const entry = payload[0]?.payload;
    if (entry === undefined) {
        return undefined;
    }
    const metricLabel = metric === "passRate" ? "Pass rate" : "Median duration";
    const rawValue = payload[0]?.value;
    const metricValue =
        typeof rawValue === "number"
            ? metric === "passRate"
              ? formatPercentValue(rawValue)
              : formatDurationValue(rawValue)
            : "-";
    return (
        <div className="border-border/50 bg-background grid min-w-[12rem] gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
            <div className="font-medium">{entry.label}</div>
            <div className="grid gap-1">
                <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">{metricLabel}</span>
                    <span className="font-medium tabular-nums">
                        {metricValue}
                    </span>
                </div>
                <div className="text-muted-foreground flex flex-col gap-1">
                    <div className="flex items-center justify-between gap-3">
                        <span>Chatbot</span>
                        <span className="text-foreground">
                            {formatModelValue(entry.chatbotModel)}
                        </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                        <span>Guardrails</span>
                        <span className="text-foreground">
                            {formatModelValue(entry.guardrailsModel)}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export const EvalsReportTrendsView = ({
    compareGroupReports,
    compareReportsOpen,
    compareReportsSearch,
    compareSelectedIds,
    compareType,
    compareTypeOptions,
    onClearCompareReports,
    onCompareReportsOpenChange,
    onCompareReportsSearchChange,
    onCompareTypeChange,
    onSelectAllCompareReports,
    onToggleCompareReport,
    onViewModeChange,
    viewMode,
}: EvalsReportTrendsViewProps): JSX.Element => {
    const compareTypeSelectLabel = compareType ?? "Select type";
    const compareSelectedSet = useMemo(
        () => new Set(compareSelectedIds),
        [compareSelectedIds],
    );

    const compareReportsLabel =
        compareSelectedIds.length === 0
            ? "Select reports"
            : `${formatOptionalNumber(compareSelectedIds.length)} report${
                  compareSelectedIds.length === 1 ? "" : "s"
              } selected`;

    const compareReportsEmptyLabel =
        compareGroupReports.length === 0
            ? "No reports available."
            : "No reports match your search.";

    const filteredCompareReports = useMemo(() => {
        const query = compareReportsSearch.trim().toLowerCase();
        if (query === "") {
            return compareGroupReports;
        }
        return compareGroupReports.filter((report) => {
            const label = `${formatTimestamp(report.generatedAt)} ${report.title}`;
            return label.toLowerCase().includes(query);
        });
    }, [compareGroupReports, compareReportsSearch]);

    const compareSelectedReports = useMemo(
        () =>
            compareGroupReports.filter((report) =>
                compareSelectedSet.has(report.id),
            ),
        [compareGroupReports, compareSelectedSet],
    );

    const compareSelectedReportsSorted = useMemo(() => {
        const reportsSorted = [...compareSelectedReports];
        reportsSorted.sort(
            (left, right) =>
                new Date(left.generatedAt).getTime() -
                new Date(right.generatedAt).getTime(),
        );
        return reportsSorted;
    }, [compareSelectedReports]);

    const compareChartData = useMemo(
        () =>
            compareSelectedReportsSorted.map((report) => {
                const roleMap = buildModelRoleMap(report);
                return {
                    id: report.id,
                    label: formatTimestamp(report.generatedAt),
                    passRate: report.passRateAverage,
                    duration: report.durationMedianAverage,
                    chatbotModel: roleMap.chatbot,
                    guardrailsModel: roleMap.guardrails,
                } satisfies CompareChartDatum;
            }),
        [compareSelectedReportsSorted],
    );

    const compareChartsHaveData = compareChartData.some(
        (entry) =>
            entry.passRate !== undefined || entry.duration !== undefined,
    );

    return (
        <>
            <div className="flex shrink-0 flex-col gap-3 pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-muted-foreground min-w-0 text-sm break-words">
                        {compareType ?? "Select a report type to view trends."}
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
                        No eval reports are available to trend yet.
                    </div>
                ) : (
                    <div className="flex flex-col gap-4">
                        <div className="grid gap-3 @lg/main:grid-cols-[1fr_1fr]">
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
                                    Reports
                                </Label>
                                <Popover
                                    onOpenChange={(nextOpen) => {
                                        onCompareReportsOpenChange(nextOpen);
                                        if (!nextOpen) {
                                            onCompareReportsSearchChange("");
                                        }
                                    }}
                                    open={compareReportsOpen}
                                >
                                    <PopoverTrigger
                                        render={
                                            <Button
                                                aria-expanded={compareReportsOpen}
                                                className="h-9 justify-between"
                                                role="combobox"
                                                type="button"
                                                variant="outline"
                                            >
                                                <span className="truncate">
                                                    {compareReportsLabel}
                                                </span>
                                                <ChevronsUpDown className="text-muted-foreground" />
                                            </Button>
                                        }
                                    />
                                    <PopoverContent
                                        align="start"
                                        className="w-[340px] p-0"
                                    >
                                        <Command shouldFilter={false}>
                                            <CommandInput
                                                onValueChange={
                                                    onCompareReportsSearchChange
                                                }
                                                placeholder="Search..."
                                                value={compareReportsSearch}
                                            />
                                            <div className="text-muted-foreground flex items-center justify-between gap-2 border-b px-3 py-2 text-xs">
                                                <span>
                                                    {compareGroupReports.length}{" "}
                                                    available
                                                </span>
                                                <div className="flex items-center gap-2">
                                                    <Button
                                                        disabled={
                                                            compareGroupReports.length ===
                                                            0
                                                        }
                                                        onClick={
                                                            onSelectAllCompareReports
                                                        }
                                                        size="sm"
                                                        type="button"
                                                        variant="ghost"
                                                    >
                                                        Select all
                                                    </Button>
                                                    <Button
                                                        disabled={
                                                            compareSelectedIds.length ===
                                                            0
                                                        }
                                                        onClick={
                                                            onClearCompareReports
                                                        }
                                                        size="sm"
                                                        type="button"
                                                        variant="ghost"
                                                    >
                                                        Clear
                                                    </Button>
                                                </div>
                                            </div>
                                            <CommandList>
                                                <CommandEmpty>
                                                    {compareReportsEmptyLabel}
                                                </CommandEmpty>
                                                <CommandGroup>
                                                    {filteredCompareReports.map(
                                                        (report) => {
                                                            const isSelected =
                                                                compareSelectedSet.has(
                                                                    report.id,
                                                                );
                                                            return (
                                                                <CommandItem
                                                                    key={
                                                                        report.id
                                                                    }
                                                                    onSelect={() => {
                                                                        onToggleCompareReport(
                                                                            report.id,
                                                                        );
                                                                    }}
                                                                    value={
                                                                        report.id
                                                                    }
                                                                >
                                                                    <Check
                                                                        className={
                                                                            isSelected
                                                                                ? "opacity-100"
                                                                                : "opacity-0"
                                                                        }
                                                                    />
                                                                    <span className="flex flex-col text-left">
                                                                        <span>
                                                                            {formatTimestamp(
                                                                                report.generatedAt,
                                                                            )}
                                                                        </span>
                                                                        <span className="text-muted-foreground text-xs">
                                                                            {
                                                                                report.title
                                                                            }
                                                                        </span>
                                                                    </span>
                                                                </CommandItem>
                                                            );
                                                        },
                                                    )}
                                                </CommandGroup>
                                            </CommandList>
                                        </Command>
                                    </PopoverContent>
                                </Popover>
                                {compareSelectedReports.length > 0 && (
                                    <div className="flex flex-wrap gap-2 pt-2">
                                        {compareSelectedReportsSorted.map(
                                            (report) => (
                                                <Badge
                                                    className="gap-1"
                                                    key={report.id}
                                                    variant="secondary"
                                                >
                                                    <span>
                                                        {formatTimestamp(
                                                            report.generatedAt,
                                                        )}
                                                    </span>
                                                    <button
                                                        aria-label={`Remove ${report.title}`}
                                                        className="text-muted-foreground hover:text-foreground"
                                                        onClick={(event) => {
                                                            event.stopPropagation();
                                                            onToggleCompareReport(
                                                                report.id,
                                                            );
                                                        }}
                                                        type="button"
                                                    >
                                                        <X className="size-3" />
                                                    </button>
                                                </Badge>
                                            ),
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                        <div className="flex flex-col gap-2">
                            <div className="text-foreground text-xs font-semibold">
                                Trends
                            </div>
                            {compareSelectedReports.length === 0 ? (
                                <div className="text-muted-foreground text-sm">
                                    Select reports to view chart trends.
                                </div>
                            ) : compareChartsHaveData ? (
                                <div className="grid gap-4 @lg/main:grid-cols-2">
                                    <div className="rounded-md border p-3">
                                        <div className="text-muted-foreground text-xs">
                                            Pass rate
                                        </div>
                                        <ChartContainer
                                            className="aspect-auto h-[220px] w-full"
                                            config={passRateChartConfig}
                                        >
                                            <BarChart data={compareChartData}>
                                                <CartesianGrid vertical={false} />
                                                <XAxis
                                                    angle={-20}
                                                    axisLine={false}
                                                    dataKey="label"
                                                    height={60}
                                                    interval={0}
                                                    textAnchor="end"
                                                    tickLine={false}
                                                    tickMargin={8}
                                                />
                                                <YAxis
                                                    axisLine={false}
                                                    domain={[0, 1]}
                                                    tickFormatter={(value) =>
                                                        `${Math.round(value * 100)}%`
                                                    }
                                                    tickLine={false}
                                                    width={48}
                                                />
                                                <ChartTooltip
                                                    content={
                                                        <CompareChartTooltip metric="passRate" />
                                                    }
                                                    cursor={false}
                                                />
                                                <Bar
                                                    dataKey="passRate"
                                                    fill="var(--color-passRate)"
                                                    radius={4}
                                                />
                                            </BarChart>
                                        </ChartContainer>
                                    </div>
                                    <div className="rounded-md border p-3">
                                        <div className="text-muted-foreground text-xs">
                                            Median duration
                                        </div>
                                        <ChartContainer
                                            className="aspect-auto h-[220px] w-full"
                                            config={durationChartConfig}
                                        >
                                            <BarChart data={compareChartData}>
                                                <CartesianGrid vertical={false} />
                                                <XAxis
                                                    angle={-20}
                                                    axisLine={false}
                                                    dataKey="label"
                                                    height={60}
                                                    interval={0}
                                                    textAnchor="end"
                                                    tickLine={false}
                                                    tickMargin={8}
                                                />
                                                <YAxis
                                                    axisLine={false}
                                                    tickFormatter={(
                                                        value: number,
                                                    ) => formatDurationValue(value)}
                                                    tickLine={false}
                                                    width={56}
                                                />
                                                <ChartTooltip
                                                    content={
                                                        <CompareChartTooltip metric="duration" />
                                                    }
                                                    cursor={false}
                                                />
                                                <Bar
                                                    dataKey="duration"
                                                    fill="var(--color-duration)"
                                                    radius={4}
                                                />
                                            </BarChart>
                                        </ChartContainer>
                                    </div>
                                </div>
                            ) : (
                                <div className="text-muted-foreground text-sm">
                                    No summary data available for the selected
                                    reports.
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </>
    );
};
