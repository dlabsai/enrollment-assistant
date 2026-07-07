import { Streamdown } from "@va/shared/components/streamdown";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { Input } from "@va/shared/components/ui/input";
import { Label } from "@va/shared/components/ui/label";
import {
    Select,
    SelectContent,
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
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import { type JSX, memo, useMemo, useState } from "react";

import {
    buildOverallAverages,
    buildScoreSummaryRows,
    formatDurationValue,
    formatEvalAudience,
    formatModelValue,
    formatOptionalNumber,
    formatPercentValue,
    formatTimestamp,
    numberFromUnknown,
    parseModelConfigurations,
    parseSummaryTable,
} from "../lib/report-utils";
import type {
    EvalCaseResult,
    EvalCaseRunResult,
    EvalEvaluationResult,
    EvalReportDetail,
} from "../types";
import { TestCaseSelector } from "./test-case-selector";

type RunStatusFilter = "all" | "failed" | "passed" | "runtime_error";
type CasePassRateFilter =
    | "all"
    | "below_threshold"
    | "partial"
    | "zero"
    | "perfect";
type ResponseRenderMode = "source" | "markdown";

interface FilteredCaseResult {
    caseResult: EvalCaseResult;
    runs: EvalCaseRunResult[];
}

interface SearchIndexedRun {
    run: EvalCaseRunResult;
    searchText: string;
}

interface SearchIndexedCase {
    caseResult: EvalCaseResult;
    runs: SearchIndexedRun[];
    searchText: string;
    testCaseId: string;
}

interface RunResultProps {
    responseRenderMode: ResponseRenderMode;
    run: EvalCaseRunResult;
    setResponseRenderMode: (value: ResponseRenderMode) => void;
}

interface EvalsReportDetailProps {
    report: EvalReportDetail;
}

const ALL_ASSERTIONS_FILTER = "all";

const JsonBlock = ({ value }: { value: unknown }): JSX.Element => (
    <pre className="bg-muted/40 max-h-72 overflow-auto rounded-md border p-3 text-xs whitespace-pre-wrap">
        {JSON.stringify(value, null, 2)}
    </pre>
);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && !Array.isArray(value);

const formatFieldLabel = (value: string): string =>
    value
        .replaceAll("_", " ")
        .replaceAll("-", " ")
        .replaceAll(/\b\w/gu, (char) => char.toUpperCase());

const FieldValue = ({ value }: { value: unknown }): JSX.Element => {
    if (typeof value === "string") {
        return <span className="whitespace-pre-wrap">{value}</span>;
    }
    if (
        typeof value === "number" ||
        typeof value === "boolean" ||
        value === null
    ) {
        return <span>{String(value)}</span>;
    }
    return <JsonBlock value={value} />;
};

const EMPTY_EXCLUDED_KEYS: string[] = [];

const FieldDetails = ({
    excludeKeys = EMPTY_EXCLUDED_KEYS,
    value,
}: {
    excludeKeys?: string[];
    value: unknown;
}): JSX.Element => {
    if (!isRecord(value)) {
        return <FieldValue value={value} />;
    }
    const excluded = new Set(excludeKeys);
    const entries = Object.entries(value).filter(([key]) => !excluded.has(key));
    if (entries.length === 0) {
        return <span className="text-muted-foreground text-xs">No data.</span>;
    }
    return (
        <div className="rounded-md border p-3 text-xs">
            <div className="grid gap-3 @lg/main:grid-cols-[10rem_minmax(0,1fr)]">
                {entries.map(([key, entryValue]) => (
                    <div
                        className="contents"
                        key={key}
                    >
                        <div className="text-muted-foreground font-medium">
                            {formatFieldLabel(key)}
                        </div>
                        <div className="min-w-0 break-words">
                            <FieldValue value={entryValue} />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

const inputUserValue = (inputs: unknown): unknown => {
    if (isRecord(inputs) && typeof inputs.user_input === "string") {
        return inputs.user_input;
    }
    return inputs;
};

const inputCriteriaValue = (inputs: unknown): string | undefined => {
    if (isRecord(inputs) && typeof inputs.criteria === "string") {
        const criteria = inputs.criteria.trim();
        return criteria === "" ? undefined : criteria;
    }
    return undefined;
};

const caseTestCaseId = (caseResult: EvalCaseResult): string => {
    if (
        isRecord(caseResult.inputs) &&
        typeof caseResult.inputs.test_case_id === "string" &&
        caseResult.inputs.test_case_id.trim() !== ""
    ) {
        return caseResult.inputs.test_case_id;
    }
    return caseResult.name;
};

const hasExpectedOutputValue = (value: unknown): boolean =>
    value !== undefined && value !== null && value !== "";

const CaseInputDetails = ({ inputs }: { inputs: unknown }): JSX.Element => (
    <div className="flex flex-col gap-2">
        <div className="text-foreground text-xs font-semibold">Input</div>
        <div className="rounded-md border p-3 text-xs">
            <FieldValue value={inputUserValue(inputs)} />
        </div>
    </div>
);

const ExpectedOutputDetails = ({
    expectedOutput,
    inputs,
}: {
    expectedOutput: unknown;
    inputs: unknown;
}): JSX.Element | undefined => {
    const criteria = inputCriteriaValue(inputs);
    const showExpectedOutput = hasExpectedOutputValue(expectedOutput);
    if (!showExpectedOutput && criteria === undefined) {
        return undefined;
    }
    return (
        <div className="flex flex-col gap-2">
            <div className="text-foreground text-xs font-semibold">
                Expected output
            </div>
            <div className="rounded-md border p-3 text-xs">
                <div className="flex flex-col gap-3">
                    {showExpectedOutput && (
                        <FieldValue value={expectedOutput} />
                    )}
                    {criteria !== undefined && (
                        <div
                            className={
                                showExpectedOutput ? "border-t pt-3" : undefined
                            }
                        >
                            <div className="text-muted-foreground mb-1 font-medium">
                                Criteria
                            </div>
                            <div className="whitespace-pre-wrap">
                                {criteria}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

const extractResponseOutput = (output: unknown): unknown => {
    if (!isRecord(output)) {
        return output;
    }
    for (const key of ["chatbot_response", "response"]) {
        if (key in output) {
            return output[key];
        }
    }
    const responseEntry = Object.entries(output).find(([key]) =>
        key.endsWith("_response"),
    );
    return responseEntry?.[1];
};

const ResponseBlock = ({
    output,
    renderMode,
}: {
    output: unknown;
    renderMode: ResponseRenderMode;
}): JSX.Element => {
    const response = extractResponseOutput(output);
    if (response === undefined || response === null || response === "") {
        return (
            <div className="text-muted-foreground min-h-72 flex-1 rounded-md border p-3 text-xs">
                No response output.
            </div>
        );
    }
    if (typeof response === "string") {
        return (
            <div className="bg-muted/40 min-h-72 flex-1 overflow-auto rounded-md border p-3 text-xs whitespace-pre-wrap">
                {renderMode === "markdown" ? (
                    <Streamdown className="max-w-none text-xs break-words">
                        {response}
                    </Streamdown>
                ) : (
                    response
                )}
            </div>
        );
    }
    return (
        <div className="min-h-72 flex-1 overflow-auto">
            <FieldDetails value={response} />
        </div>
    );
};

const InlineJsonValue = ({ value }: { value: unknown }): JSX.Element => {
    if (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
    ) {
        return <span>{String(value)}</span>;
    }
    if (value === null) {
        return <span>null</span>;
    }
    return <code className="text-xs break-words">{JSON.stringify(value)}</code>;
};

const statusVariant = (
    status: string,
): "secondary" | "destructive" | "outline" => {
    if (status === "threshold_failed" || status === "error") {
        return "destructive";
    }
    if (status === "complete") {
        return "outline";
    }
    return "secondary";
};

const formatStatus = (status: string): string =>
    status.replaceAll("_", " ").replace(/^./u, (char) => char.toUpperCase());

const ResultBadge = ({
    result,
}: {
    result: EvalEvaluationResult;
}): JSX.Element => {
    if (typeof result.value === "boolean") {
        return (
            <Badge variant={result.value ? "outline" : "destructive"}>
                {result.value ? "Pass" : "Fail"}
            </Badge>
        );
    }
    return <span className="tabular-nums">{String(result.value)}</span>;
};

const resultRowClassName = (result: EvalEvaluationResult): string => {
    if (result.value === false) {
        return "border-destructive/30 bg-destructive/5";
    }
    return "bg-background/60";
};

const ResultMap = ({
    results,
    showReason,
    title,
}: {
    results: Record<string, EvalEvaluationResult>;
    showReason?: boolean;
    title: string;
}): JSX.Element | undefined => {
    const entries = Object.entries(results);
    if (entries.length === 0) {
        return undefined;
    }
    const shouldShowReason =
        showReason ?? entries.some(([, result]) => result.reason !== null);
    return (
        <div className="flex flex-col gap-2">
            <div className="text-foreground text-xs font-semibold">{title}</div>
            <div className="flex flex-col gap-2">
                {entries.map(([key, result]) => (
                    <div
                        className={`rounded-md border p-3 text-xs ${resultRowClassName(result)}`}
                        key={key}
                    >
                        <div className="flex flex-wrap items-center gap-2">
                            <div className="font-medium break-words">
                                {result.name || key}
                            </div>
                            <ResultBadge result={result} />
                        </div>
                        {shouldShowReason && result.reason !== null && (
                            <div className="text-muted-foreground mt-2 break-words whitespace-pre-wrap">
                                {result.reason}
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
};

const RunResult = memo(
    ({
        responseRenderMode,
        run,
        setResponseRenderMode,
    }: RunResultProps): JSX.Element => (
        <Card className="bg-muted/10">
            <CardHeader className="gap-2 pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-sm">
                        Run {run.runIndex}
                    </CardTitle>
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="text-muted-foreground tabular-nums">
                            {formatDurationValue(run.duration)}
                        </span>
                        {run.error === null ? (
                            <Badge variant="outline">Completed</Badge>
                        ) : (
                            <Badge variant="destructive">Error</Badge>
                        )}
                        {run.otelTraceId !== null && (
                            <a
                                className="text-primary hover:underline"
                                href={`#/eval-traces/${encodeURIComponent(run.otelTraceId)}${
                                    run.otelSpanId === null
                                        ? "?view=summary"
                                        : `?span=${encodeURIComponent(run.otelSpanId)}&view=summary`
                                }`}
                                rel="noreferrer"
                                target="_blank"
                            >
                                Trace
                            </a>
                        )}
                    </div>
                </div>
                {run.error !== null && (
                    <CardDescription className="text-destructive whitespace-pre-wrap">
                        {run.error}
                    </CardDescription>
                )}
            </CardHeader>
            <CardContent>
                <div className="grid gap-4 @lg/main:grid-cols-2">
                    <div className="flex h-full flex-col gap-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-foreground text-xs font-semibold">
                                Response
                            </div>
                            <ToggleGroup
                                onValueChange={(value) => {
                                    const [nextValue] = value;
                                    if (
                                        nextValue === "source" ||
                                        nextValue === "markdown"
                                    ) {
                                        setResponseRenderMode(nextValue);
                                    }
                                }}
                                size="sm"
                                value={[responseRenderMode]}
                                variant="outline"
                            >
                                <ToggleGroupItem value="source">
                                    Source
                                </ToggleGroupItem>
                                <ToggleGroupItem value="markdown">
                                    Markdown
                                </ToggleGroupItem>
                            </ToggleGroup>
                        </div>
                        <ResponseBlock
                            output={run.output}
                            renderMode={responseRenderMode}
                        />
                    </div>
                    <div className="flex flex-col gap-4">
                        <ResultMap
                            results={run.assertions}
                            title="Assertions"
                        />
                        <ResultMap
                            results={run.scores}
                            showReason={false}
                            title="Metrics"
                        />
                        <ResultMap
                            results={run.labels}
                            showReason={false}
                            title="Labels"
                        />
                    </div>
                </div>
            </CardContent>
        </Card>
    ),
);
RunResult.displayName = "RunResult";

const CaseContextHeader = ({
    badge,
    caseResult,
}: {
    badge?: JSX.Element;
    caseResult: EvalCaseResult;
}): JSX.Element => (
    <div className="bg-card sticky top-0 z-10 border-b">
        <CardHeader className="gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-base break-words">
                    {caseResult.name}
                </CardTitle>
                {badge}
            </div>
            <CardDescription>
                Pass rate{" "}
                {formatPercentValue(
                    numberFromUnknown(caseResult.stats.pass_rate),
                )}{" "}
                · Runtime errors{" "}
                {formatPercentValue(
                    numberFromUnknown(caseResult.stats.runtime_error_rate),
                )}
            </CardDescription>
        </CardHeader>
        <CardContent className="pb-4">
            <div className="grid gap-4 @lg/main:grid-cols-2">
                <CaseInputDetails inputs={caseResult.inputs} />
                <ExpectedOutputDetails
                    expectedOutput={caseResult.expectedOutput}
                    inputs={caseResult.inputs}
                />
            </div>
        </CardContent>
    </div>
);

const runHasFailure = (run: EvalCaseRunResult): boolean =>
    run.error !== null ||
    Object.values(run.assertions).some((result) => result.value === false);

const runHasFailedAssertion = (
    run: EvalCaseRunResult,
    assertionName: string,
): boolean => run.assertions[assertionName]?.value === false;

const stringifySearchValue = (value: unknown): string => {
    if (value === undefined || value === null) {
        return "";
    }
    if (typeof value === "string") {
        return value;
    }
    if (
        typeof value === "number" ||
        typeof value === "boolean" ||
        typeof value === "bigint"
    ) {
        return String(value);
    }
    try {
        return JSON.stringify(value);
    } catch {
        return "";
    }
};

const caseSearchText = (caseResult: EvalCaseResult): string =>
    [
        caseResult.name,
        stringifySearchValue(caseResult.inputs),
        stringifySearchValue(caseResult.expectedOutput),
        stringifySearchValue(caseResult.metadata),
        stringifySearchValue(caseResult.stats),
    ]
        .join("\n")
        .toLowerCase();

const runSearchText = (run: EvalCaseRunResult): string =>
    [
        run.runIndex,
        run.error,
        run.otelTraceId,
        run.otelSpanId,
        stringifySearchValue(run.output),
        stringifySearchValue(run.assertions),
        stringifySearchValue(run.scores),
        stringifySearchValue(run.labels),
    ]
        .join("\n")
        .toLowerCase();

const caseMatchesPassRateFilter = (
    caseResult: EvalCaseResult,
    filter: CasePassRateFilter,
    threshold: number,
): boolean => {
    if (filter === "all") {
        return true;
    }
    const passRate = numberFromUnknown(caseResult.stats.pass_rate);
    if (passRate === undefined) {
        return false;
    }
    if (filter === "below_threshold") {
        return passRate < threshold;
    }
    if (filter === "partial") {
        return passRate > 0 && passRate < 1;
    }
    if (filter === "zero") {
        return passRate === 0;
    }
    return passRate === 1;
};

const runMatchesStatusFilter = (
    run: EvalCaseRunResult,
    filter: RunStatusFilter,
): boolean => {
    if (filter === "all") {
        return true;
    }
    if (filter === "failed") {
        return runHasFailure(run);
    }
    if (filter === "passed") {
        return !runHasFailure(run);
    }
    return run.error !== null;
};

const guardrailRetriesValue = (run: EvalCaseRunResult): number | undefined => {
    const value = run.scores.guardrail_retries?.value;
    return typeof value === "number" ? value : undefined;
};

const runMatchesGuardrailRetriesFilter = (
    run: EvalCaseRunResult,
    filter: string,
): boolean => {
    if (filter === "all") {
        return true;
    }
    const retries = guardrailRetriesValue(run);
    return retries !== undefined && String(retries) === filter;
};

export const EvalsReportDetail = memo(
    ({ report }: EvalsReportDetailProps): JSX.Element => {
        const [searchQuery, setSearchQuery] = useState("");
        const [runStatusFilter, setRunStatusFilter] =
            useState<RunStatusFilter>("all");
        const [assertionFilter, setAssertionFilter] = useState(
            ALL_ASSERTIONS_FILTER,
        );
        const [casePassRateFilter, setCasePassRateFilter] =
            useState<CasePassRateFilter>("all");
        const [guardrailRetriesFilter, setGuardrailRetriesFilter] =
            useState("all");
        const [selectedTestCaseIds, setSelectedTestCaseIds] = useState<
            string[]
        >([]);
        const [responseRenderMode, setResponseRenderMode] =
            useState<ResponseRenderMode>("source");
        const summaries = useMemo(() => parseSummaryTable(report), [report]);
        const modelConfigs = useMemo(
            () => parseModelConfigurations(report),
            [report],
        );
        const additionalSettings = useMemo(
            () => Object.entries(report.additionalSettings),
            [report.additionalSettings],
        );
        const scoreSummaryRows = useMemo(
            () => buildScoreSummaryRows(report),
            [report],
        );
        const overallAverages = useMemo(
            () => buildOverallAverages(report),
            [report],
        );
        const searchIndexedCases = useMemo<SearchIndexedCase[]>(
            () =>
                report.cases.map((caseResult) => ({
                    caseResult,
                    runs: caseResult.runs.map((run) => ({
                        run,
                        searchText: runSearchText(run),
                    })),
                    searchText: caseSearchText(caseResult),
                    testCaseId: caseTestCaseId(caseResult),
                })),
            [report.cases],
        );
        const assertionNames = useMemo(
            () =>
                [
                    ...new Set(
                        report.cases.flatMap((caseResult) =>
                            caseResult.runs.flatMap((run) =>
                                Object.keys(run.assertions),
                            ),
                        ),
                    ),
                ].toSorted((left, right) => left.localeCompare(right)),
            [report.cases],
        );
        const guardrailRetryValues = useMemo(
            () =>
                [
                    ...new Set(
                        report.cases.flatMap((caseResult) =>
                            caseResult.runs.flatMap((run) => {
                                const retries = guardrailRetriesValue(run);
                                return retries === undefined ? [] : [retries];
                            }),
                        ),
                    ),
                ].toSorted((left, right) => left - right),
            [report.cases],
        );
        const testCaseIdOptions = useMemo(
            () =>
                [
                    ...new Set(
                        searchIndexedCases.map(
                            (caseResult) => caseResult.testCaseId,
                        ),
                    ),
                ].toSorted((left, right) => left.localeCompare(right)),
            [searchIndexedCases],
        );
        const selectedTestCaseIdSet = useMemo(
            () => new Set(selectedTestCaseIds),
            [selectedTestCaseIds],
        );
        const filteredCases = useMemo<FilteredCaseResult[]>(() => {
            const query = searchQuery.trim().toLowerCase();
            return searchIndexedCases.flatMap((indexedCase) => {
                const {
                    caseResult,
                    runs: indexedRuns,
                    searchText,
                    testCaseId,
                } = indexedCase;
                if (
                    selectedTestCaseIdSet.size > 0 &&
                    !selectedTestCaseIdSet.has(testCaseId)
                ) {
                    return [];
                }
                if (
                    !caseMatchesPassRateFilter(
                        caseResult,
                        casePassRateFilter,
                        report.passThreshold,
                    )
                ) {
                    return [];
                }
                const caseMatchesQuery =
                    query === "" || searchText.includes(query);
                const runs = indexedRuns
                    .filter(({ run, searchText: runSearchTextValue }) => {
                        const matchesAssertion =
                            assertionFilter === ALL_ASSERTIONS_FILTER ||
                            runHasFailedAssertion(run, assertionFilter);
                        const matchesQuery =
                            query === "" ||
                            caseMatchesQuery ||
                            runSearchTextValue.includes(query);
                        return (
                            runMatchesStatusFilter(run, runStatusFilter) &&
                            runMatchesGuardrailRetriesFilter(
                                run,
                                guardrailRetriesFilter,
                            ) &&
                            matchesAssertion &&
                            matchesQuery
                        );
                    })
                    .map(({ run }) => run);
                if (runs.length === 0) {
                    return [];
                }
                return [{ caseResult, runs }];
            });
        }, [
            assertionFilter,
            casePassRateFilter,
            guardrailRetriesFilter,
            report.passThreshold,
            searchIndexedCases,
            runStatusFilter,
            selectedTestCaseIdSet,
            searchQuery,
        ]);
        const filterActive =
            searchQuery.trim() !== "" ||
            runStatusFilter !== "all" ||
            assertionFilter !== ALL_ASSERTIONS_FILTER ||
            guardrailRetriesFilter !== "all" ||
            selectedTestCaseIds.length > 0 ||
            casePassRateFilter !== "all";
        const filteredRunCount = useMemo(
            () =>
                filteredCases.reduce(
                    (total, entry) => total + entry.runs.length,
                    0,
                ),
            [filteredCases],
        );
        const resetFilters = (): void => {
            setSearchQuery("");
            setRunStatusFilter("all");
            setAssertionFilter(ALL_ASSERTIONS_FILTER);
            setGuardrailRetriesFilter("all");
            setSelectedTestCaseIds([]);
            setCasePassRateFilter("all");
        };
        const failedCases = useMemo(
            () =>
                filteredCases
                    .map((caseResult) => ({
                        caseResult: caseResult.caseResult,
                        runs: caseResult.runs.filter((run) =>
                            runHasFailure(run),
                        ),
                    }))
                    .filter((entry) => entry.runs.length > 0),
            [filteredCases],
        );

        return (
            <div className="flex flex-col gap-6">
                <div className="grid gap-3 @lg/main:grid-cols-6">
                    <div className="rounded-md border p-3">
                        <div className="text-muted-foreground text-xs">
                            Status
                        </div>
                        <Badge
                            className="mt-1"
                            variant={statusVariant(report.status)}
                        >
                            {formatStatus(report.status)}
                        </Badge>
                    </div>
                    <div className="rounded-md border p-3">
                        <div className="text-muted-foreground text-xs">
                            Cases
                        </div>
                        <div className="text-xl font-semibold tabular-nums">
                            {formatOptionalNumber(report.caseCount)}
                        </div>
                    </div>
                    <div className="rounded-md border p-3">
                        <div className="text-muted-foreground text-xs">
                            Runs
                        </div>
                        <div className="text-xl font-semibold tabular-nums">
                            {formatOptionalNumber(report.runCount)}
                        </div>
                    </div>
                    <div className="rounded-md border p-3">
                        <div className="text-muted-foreground text-xs">
                            Threshold
                        </div>
                        <div className="text-xl font-semibold tabular-nums">
                            {formatPercentValue(report.passThreshold)}
                        </div>
                    </div>
                    {report.isInternal !== null && (
                        <div className="rounded-md border p-3">
                            <div className="text-muted-foreground text-xs">
                                Audience
                            </div>
                            <div className="text-sm font-semibold">
                                {formatEvalAudience(report.isInternal)}
                            </div>
                        </div>
                    )}
                </div>

                <div className="text-muted-foreground flex flex-wrap gap-2 text-xs">
                    <span>Generated {formatTimestamp(report.generatedAt)}</span>
                    <span>•</span>
                    <span>Suite {report.suite}</span>
                    <span>•</span>
                    <span>Repeats {formatOptionalNumber(report.repeats)}</span>
                    <span>•</span>
                    <span>
                        Concurrency {formatOptionalNumber(report.concurrency)}
                    </span>
                </div>

                {modelConfigs.length > 0 && (
                    <div className="flex flex-col gap-2">
                        <div className="text-foreground text-xs font-semibold">
                            Models
                        </div>
                        <div className="overflow-x-auto rounded-md border">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Role</TableHead>
                                        <TableHead>Model</TableHead>
                                        <TableHead className="text-right">
                                            Temperature
                                        </TableHead>
                                        <TableHead className="text-right">
                                            Max tokens
                                        </TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {modelConfigs.map((config) => (
                                        <TableRow key={config.role}>
                                            <TableCell className="font-medium">
                                                {config.role}
                                            </TableCell>
                                            <TableCell className="text-xs break-words">
                                                {formatModelValue(config.model)}
                                            </TableCell>
                                            <TableCell className="text-right tabular-nums">
                                                {formatOptionalNumber(
                                                    config.temperature,
                                                )}
                                            </TableCell>
                                            <TableCell className="text-right tabular-nums">
                                                {formatOptionalNumber(
                                                    config.maxTokens,
                                                )}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    </div>
                )}

                {additionalSettings.length > 0 && (
                    <div className="flex flex-col gap-2">
                        <div className="text-foreground text-xs font-semibold">
                            Additional settings
                        </div>
                        <div className="overflow-x-auto rounded-md border">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Setting</TableHead>
                                        <TableHead>Value</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {additionalSettings.map(([key, value]) => (
                                        <TableRow key={key}>
                                            <TableCell className="font-medium">
                                                {key.replaceAll("_", " ")}
                                            </TableCell>
                                            <TableCell className="text-xs break-words">
                                                <InlineJsonValue
                                                    value={value}
                                                />
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    </div>
                )}

                <div className="flex flex-col gap-2">
                    <div className="text-foreground text-xs font-semibold">
                        Summary
                    </div>
                    <div className="overflow-x-auto rounded-md border">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Case</TableHead>
                                    <TableHead className="text-right">
                                        Runs
                                    </TableHead>
                                    <TableHead className="text-right">
                                        Pass rate
                                    </TableHead>
                                    <TableHead className="text-right">
                                        Runtime errors
                                    </TableHead>
                                    <TableHead className="text-right">
                                        Duration min / med / max
                                    </TableHead>
                                    <TableHead>Assertions</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {summaries.map((summary) => (
                                    <TableRow key={summary.caseName}>
                                        <TableCell className="font-medium break-words">
                                            {summary.caseName}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">
                                            {formatOptionalNumber(summary.runs)}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">
                                            {formatPercentValue(
                                                summary.passRate,
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">
                                            {formatPercentValue(
                                                summary.runtimeErrorRate,
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right tabular-nums">
                                            {formatDurationValue(
                                                summary.durationMin,
                                            )}{" "}
                                            /{" "}
                                            {formatDurationValue(
                                                summary.durationMedian,
                                            )}{" "}
                                            /{" "}
                                            {formatDurationValue(
                                                summary.durationMax,
                                            )}
                                        </TableCell>
                                        <TableCell className="text-xs break-words">
                                            {summary.assertions || "-"}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                </div>

                {scoreSummaryRows.length > 0 && (
                    <div className="flex flex-col gap-2">
                        <div className="text-foreground text-xs font-semibold">
                            Scores
                        </div>
                        <div className="overflow-x-auto rounded-md border">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Case</TableHead>
                                        <TableHead>Score</TableHead>
                                        <TableHead className="text-right">
                                            Min
                                        </TableHead>
                                        <TableHead className="text-right">
                                            Median
                                        </TableHead>
                                        <TableHead className="text-right">
                                            Max
                                        </TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {scoreSummaryRows.map((row) => (
                                        <TableRow
                                            key={`${row.caseName}:${row.scoreName}`}
                                        >
                                            <TableCell className="font-medium break-words">
                                                {row.caseName}
                                            </TableCell>
                                            <TableCell>
                                                {row.scoreName}
                                            </TableCell>
                                            <TableCell className="text-right tabular-nums">
                                                {formatOptionalNumber(row.min)}
                                            </TableCell>
                                            <TableCell className="text-right tabular-nums">
                                                {formatOptionalNumber(
                                                    row.median,
                                                )}
                                            </TableCell>
                                            <TableCell className="text-right tabular-nums">
                                                {formatOptionalNumber(row.max)}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    </div>
                )}

                {(overallAverages.assertions.length > 0 ||
                    overallAverages.scores.length > 0) && (
                    <div className="flex flex-col gap-2">
                        <div className="text-foreground text-xs font-semibold">
                            Overall averages
                        </div>
                        <div className="grid gap-4 @lg/main:grid-cols-2">
                            {overallAverages.assertions.length > 0 && (
                                <div className="overflow-x-auto rounded-md border">
                                    <Table>
                                        <TableHeader>
                                            <TableRow>
                                                <TableHead>Assertion</TableHead>
                                                <TableHead className="text-right">
                                                    Avg pass rate
                                                </TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {overallAverages.assertions.map(
                                                (entry) => (
                                                    <TableRow key={entry.name}>
                                                        <TableCell className="font-medium">
                                                            {entry.name}
                                                        </TableCell>
                                                        <TableCell className="text-right tabular-nums">
                                                            {formatPercentValue(
                                                                entry.average,
                                                            )}
                                                        </TableCell>
                                                    </TableRow>
                                                ),
                                            )}
                                        </TableBody>
                                    </Table>
                                </div>
                            )}
                            {overallAverages.scores.length > 0 && (
                                <div className="overflow-x-auto rounded-md border">
                                    <Table>
                                        <TableHeader>
                                            <TableRow>
                                                <TableHead>Score</TableHead>
                                                <TableHead className="text-right">
                                                    Average
                                                </TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {overallAverages.scores.map(
                                                (entry) => (
                                                    <TableRow key={entry.name}>
                                                        <TableCell className="font-medium">
                                                            {entry.name}
                                                        </TableCell>
                                                        <TableCell className="text-right tabular-nums">
                                                            {formatOptionalNumber(
                                                                entry.average,
                                                            )}
                                                        </TableCell>
                                                    </TableRow>
                                                ),
                                            )}
                                        </TableBody>
                                    </Table>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                <Card className="bg-muted/10">
                    <CardHeader className="gap-2 pb-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                                <CardTitle className="text-base">
                                    Report filters
                                </CardTitle>
                            </div>
                            <div className="flex items-center gap-2">
                                <Badge variant="secondary">
                                    {formatOptionalNumber(filteredCases.length)}
                                    /{formatOptionalNumber(report.cases.length)}{" "}
                                    cases ·{" "}
                                    {formatOptionalNumber(filteredRunCount)}/
                                    {formatOptionalNumber(report.runCount)} runs
                                </Badge>
                                {filterActive && (
                                    <Button
                                        onClick={resetFilters}
                                        size="sm"
                                        type="button"
                                        variant="outline"
                                    >
                                        Clear filters
                                    </Button>
                                )}
                            </div>
                        </div>
                    </CardHeader>
                    <CardContent>
                        <div className="grid gap-3 @lg/main:grid-cols-4">
                            <div className="flex flex-col gap-2 @lg/main:col-span-4">
                                <Label htmlFor="eval-report-text-filter">
                                    Free-text filter
                                </Label>
                                <Input
                                    id="eval-report-text-filter"
                                    onChange={(event) => {
                                        setSearchQuery(event.target.value);
                                    }}
                                    placeholder="Search case names, inputs, responses, reasons, errors, trace IDs..."
                                    value={searchQuery}
                                />
                            </div>
                            <div className="flex flex-col gap-2 @lg/main:col-span-4">
                                <Label>Test case IDs</Label>
                                <TestCaseSelector
                                    emptyLabel="No test cases found"
                                    onSelectedValuesChange={
                                        setSelectedTestCaseIds
                                    }
                                    options={testCaseIdOptions}
                                    placeholder="Search test case IDs..."
                                    selectedValues={selectedTestCaseIds}
                                />
                            </div>
                            <div className="flex flex-col gap-2">
                                <Label>Run status</Label>
                                <Select
                                    onValueChange={(value) => {
                                        if (value !== null) {
                                            setRunStatusFilter(
                                                value as RunStatusFilter,
                                            );
                                        }
                                    }}
                                    value={runStatusFilter}
                                >
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="all">
                                            All runs
                                        </SelectItem>
                                        <SelectItem value="failed">
                                            Failed runs
                                        </SelectItem>
                                        <SelectItem value="passed">
                                            Passed runs
                                        </SelectItem>
                                        <SelectItem value="runtime_error">
                                            Runtime errors
                                        </SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex flex-col gap-2">
                                <Label>Failed assertion</Label>
                                <Select
                                    onValueChange={(value) => {
                                        if (value !== null) {
                                            setAssertionFilter(value);
                                        }
                                    }}
                                    value={assertionFilter}
                                >
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem
                                            value={ALL_ASSERTIONS_FILTER}
                                        >
                                            Any assertion
                                        </SelectItem>
                                        {assertionNames.map((assertionName) => (
                                            <SelectItem
                                                key={assertionName}
                                                value={assertionName}
                                            >
                                                {assertionName}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex flex-col gap-2">
                                <Label>Case pass rate</Label>
                                <Select
                                    onValueChange={(value) => {
                                        if (value !== null) {
                                            setCasePassRateFilter(
                                                value as CasePassRateFilter,
                                            );
                                        }
                                    }}
                                    value={casePassRateFilter}
                                >
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="all">
                                            All cases
                                        </SelectItem>
                                        <SelectItem value="below_threshold">
                                            Below threshold
                                        </SelectItem>
                                        <SelectItem value="partial">
                                            Partial pass
                                        </SelectItem>
                                        <SelectItem value="zero">
                                            0% pass
                                        </SelectItem>
                                        <SelectItem value="perfect">
                                            100% pass
                                        </SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex flex-col gap-2">
                                <Label>Guardrail retries</Label>
                                <Select
                                    onValueChange={(value) => {
                                        if (value !== null) {
                                            setGuardrailRetriesFilter(value);
                                        }
                                    }}
                                    value={guardrailRetriesFilter}
                                >
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="all">
                                            Any retry count
                                        </SelectItem>
                                        {guardrailRetryValues.map((retries) => (
                                            <SelectItem
                                                key={retries}
                                                value={String(retries)}
                                            >
                                                {retries}{" "}
                                                {retries === 1
                                                    ? "retry"
                                                    : "retries"}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                    </CardContent>
                </Card>

                <div className="flex flex-col gap-4">
                    <div className="text-foreground text-xs font-semibold">
                        Failed runs
                    </div>
                    {failedCases.length === 0 ? (
                        <Card className="bg-muted/10">
                            <CardContent className="text-muted-foreground p-4 text-sm">
                                No failed runs.
                            </CardContent>
                        </Card>
                    ) : (
                        failedCases.map(({ caseResult, runs }) => (
                            <Card
                                className="overflow-visible"
                                key={caseResult.name}
                            >
                                <CaseContextHeader
                                    badge={
                                        <Badge variant="secondary">
                                            {formatOptionalNumber(runs.length)}{" "}
                                            failed run
                                            {runs.length === 1 ? "" : "s"}
                                        </Badge>
                                    }
                                    caseResult={caseResult}
                                />
                                <CardContent className="flex flex-col gap-4 pt-4">
                                    {runs.map((run) => (
                                        <RunResult
                                            key={run.runIndex}
                                            responseRenderMode={
                                                responseRenderMode
                                            }
                                            run={run}
                                            setResponseRenderMode={
                                                setResponseRenderMode
                                            }
                                        />
                                    ))}
                                </CardContent>
                            </Card>
                        ))
                    )}
                </div>

                <div className="flex flex-col gap-4">
                    <div className="text-foreground text-xs font-semibold">
                        Cases
                    </div>
                    {filteredCases.length === 0 ? (
                        <Card className="bg-muted/10">
                            <CardContent className="text-muted-foreground p-4 text-sm">
                                No cases match the active filters.
                            </CardContent>
                        </Card>
                    ) : (
                        filteredCases.map(({ caseResult, runs }) => (
                            <Card
                                className="overflow-visible"
                                key={caseResult.name}
                            >
                                <CaseContextHeader
                                    badge={
                                        <Badge variant="secondary">
                                            {filterActive
                                                ? `${formatOptionalNumber(runs.length)} of ${formatOptionalNumber(caseResult.runs.length)}`
                                                : formatOptionalNumber(
                                                      caseResult.runs.length,
                                                  )}{" "}
                                            run
                                            {caseResult.runs.length === 1
                                                ? ""
                                                : "s"}
                                        </Badge>
                                    }
                                    caseResult={caseResult}
                                />
                                <CardContent className="flex flex-col gap-4 pt-4">
                                    {runs.map((run) => (
                                        <RunResult
                                            key={run.runIndex}
                                            responseRenderMode={
                                                responseRenderMode
                                            }
                                            run={run}
                                            setResponseRenderMode={
                                                setResponseRenderMode
                                            }
                                        />
                                    ))}
                                </CardContent>
                            </Card>
                        ))
                    )}
                </div>
            </div>
        );
    },
);
EvalsReportDetail.displayName = "EvalsReportDetail";
