import { formatTableTimestamp } from "../../lib/date-format.ts";
import { formatLocaleNumber } from "../../lib/number-format.ts";
import type { EvalReportDetail, EvalReportSummary } from "../types";

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && !Array.isArray(value);

export const formatTimestamp = formatTableTimestamp;

export const formatOptionalNumber = (
    value: number | null | undefined,
): string =>
    value === null || value === undefined
        ? "-"
        : formatLocaleNumber(value, { maximumFractionDigits: 4 });

export const formatModelValue = (value: string | undefined): string =>
    value === undefined || value === "" ? "-" : value;

export const formatEvalAudience = (
    value: EvalReportSummary["isInternal"],
): string => {
    if (value === true) {
        return "Internal VA";
    }
    if (value === false) {
        return "Public VA";
    }
    return "Mixed/unknown";
};

export const formatReportMeta = (
    report: EvalReportSummary | EvalReportDetail,
): string => {
    const parts = [
        `Generated ${formatTimestamp(report.generatedAt)}`,
        `Repeats ${formatOptionalNumber(report.repeats)}`,
        `Concurrency ${formatOptionalNumber(report.concurrency)}`,
        `${formatLocaleNumber(report.caseCount)} cases`,
        `${formatLocaleNumber(report.runCount)} runs`,
    ];
    if (report.isInternal !== null) {
        parts.push(formatEvalAudience(report.isInternal));
    }
    return parts.join(" · ");
};

interface EvalCaseSummary {
    caseName: string;
    runs: number | undefined;
    passRate: number | undefined;
    runtimeErrorRate: number | undefined;
    durationMin: number | undefined;
    durationMedian: number | undefined;
    durationMax: number | undefined;
    assertions: string;
}

interface EvalScoreSummary {
    caseName: string;
    scoreName: string;
    min: number | undefined;
    median: number | undefined;
    max: number | undefined;
}

interface EvalOverallAssertionAverage {
    name: string;
    average: number;
}

interface EvalOverallScoreAverage {
    name: string;
    average: number;
}

interface EvalOverallAverages {
    assertions: EvalOverallAssertionAverage[];
    scores: EvalOverallScoreAverage[];
}

interface EvalCompareRow {
    caseName: string;
    left?: EvalCaseSummary;
    right?: EvalCaseSummary;
}

interface EvalModelConfig {
    role: string;
    model: string;
    temperature: number | undefined;
    maxTokens: number | undefined;
}

interface EvalModelConfigSource {
    modelConfigs: Record<string, unknown>;
}

type EvalModelRoleKey = "chatbot" | "guardrails";

interface EvalModelCompareRow {
    role: string;
    left?: EvalModelConfig;
    right?: EvalModelConfig;
}

export const numberFromUnknown = (value: unknown): number | undefined =>
    typeof value === "number" && Number.isFinite(value) ? value : undefined;

const formatPercent = (value: number | undefined): string => {
    if (value === undefined) {
        return "-";
    }
    const pct = value * 100;
    if (Number.isInteger(pct)) {
        return `${formatLocaleNumber(pct)}%`;
    }
    return `${formatLocaleNumber(pct, {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
    })}%`;
};

const formatAssertionSummary = (assertionPassRates: unknown): string => {
    if (!isRecord(assertionPassRates)) {
        return "";
    }
    return Object.entries(assertionPassRates)
        .map(([name, value]) => {
            const rate = numberFromUnknown(value);
            const status = rate === 1 ? "✓" : rate === 0 ? "✗" : "~";
            return `${status} ${name}: ${formatPercent(rate)}`;
        })
        .join(", ");
};

export const parseSummaryTable = (
    report: EvalReportDetail,
): EvalCaseSummary[] =>
    report.cases.map((caseResult) => ({
        caseName: caseResult.name,
        runs: numberFromUnknown(caseResult.stats.runs),
        passRate: numberFromUnknown(caseResult.stats.pass_rate),
        runtimeErrorRate: numberFromUnknown(
            caseResult.stats.runtime_error_rate,
        ),
        durationMin: numberFromUnknown(caseResult.stats.duration_min),
        durationMedian: numberFromUnknown(caseResult.stats.duration_median),
        durationMax: numberFromUnknown(caseResult.stats.duration_max),
        assertions: formatAssertionSummary(
            caseResult.stats.assertion_pass_rates,
        ),
    }));

export const buildScoreSummaryRows = (
    report: EvalReportDetail,
): EvalScoreSummary[] =>
    report.cases.flatMap((caseResult) => {
        const scoreMeans = caseResult.stats.score_means;
        if (!isRecord(scoreMeans)) {
            return [];
        }
        return Object.keys(scoreMeans).map((scoreName) => ({
            caseName: caseResult.name,
            scoreName,
            min: numberFromUnknown(
                isRecord(caseResult.stats.score_mins)
                    ? caseResult.stats.score_mins[scoreName]
                    : undefined,
            ),
            median: numberFromUnknown(
                isRecord(caseResult.stats.score_medians)
                    ? caseResult.stats.score_medians[scoreName]
                    : undefined,
            ),
            max: numberFromUnknown(
                isRecord(caseResult.stats.score_maxs)
                    ? caseResult.stats.score_maxs[scoreName]
                    : undefined,
            ),
        }));
    });

export const buildOverallAverages = (
    report: EvalReportDetail,
): EvalOverallAverages => {
    const assertionRates = new Map<string, number[]>();
    const scoreMeans = new Map<string, number[]>();

    for (const caseResult of report.cases) {
        if (isRecord(caseResult.stats.assertion_pass_rates)) {
            for (const [name, value] of Object.entries(
                caseResult.stats.assertion_pass_rates,
            )) {
                const rate = numberFromUnknown(value);
                if (rate !== undefined) {
                    assertionRates.set(name, [
                        ...(assertionRates.get(name) ?? []),
                        rate,
                    ]);
                }
            }
        }
        if (isRecord(caseResult.stats.score_means)) {
            for (const [name, value] of Object.entries(
                caseResult.stats.score_means,
            )) {
                const mean = numberFromUnknown(value);
                if (mean !== undefined) {
                    scoreMeans.set(name, [...(scoreMeans.get(name) ?? []), mean]);
                }
            }
        }
    }

    return {
        assertions: [...assertionRates.entries()].map(([name, values]) => ({
            name,
            average:
                values.reduce((total, value) => total + value, 0) /
                values.length,
        })),
        scores: [...scoreMeans.entries()].map(([name, values]) => ({
            name,
            average:
                values.reduce((total, value) => total + value, 0) /
                values.length,
        })),
    };
};

const resolveModelRoleKey = (role: string): EvalModelRoleKey | undefined => {
    const normalized = role.trim().toLowerCase();
    if (normalized.includes("chatbot")) {
        return "chatbot";
    }
    if (normalized.includes("guardrail")) {
        return "guardrails";
    }
    return undefined;
};

export const parseModelConfigurations = (
    report: EvalModelConfigSource,
): EvalModelConfig[] =>
    Object.entries(report.modelConfigs)
        .map(([role, rawConfig]) => {
            if (!isRecord(rawConfig)) {
                return {
                    role,
                    model: String(rawConfig),
                    temperature: undefined,
                    maxTokens: undefined,
                } satisfies EvalModelConfig;
            }
            const modelValue = rawConfig.model;
            return {
                role,
                model: typeof modelValue === "string" ? modelValue : "",
                temperature: numberFromUnknown(rawConfig.temperature),
                maxTokens: numberFromUnknown(rawConfig.max_tokens),
            } satisfies EvalModelConfig;
        })
        .toSorted((left, right) => left.role.localeCompare(right.role));

export const buildModelRoleMap = (
    report: EvalModelConfigSource,
): Partial<Record<EvalModelRoleKey, string>> => {
    const modelConfigs = parseModelConfigurations(report);
    const roles: Partial<Record<EvalModelRoleKey, string>> = {};
    for (const config of modelConfigs) {
        const roleKey = resolveModelRoleKey(config.role);
        if (roleKey !== undefined) {
            roles[roleKey] = config.model;
        }
    }
    return roles;
};

export const buildCompareRows = (
    left: EvalCaseSummary[],
    right: EvalCaseSummary[],
): EvalCompareRow[] => {
    const rightMap = new Map(
        right.map((summary) => [summary.caseName, summary]),
    );
    const leftMap = new Map(left.map((summary) => [summary.caseName, summary]));
    const rows: EvalCompareRow[] = left.map((summary) => ({
        caseName: summary.caseName,
        left: summary,
        right: rightMap.get(summary.caseName),
    }));

    for (const summary of right) {
        if (!leftMap.has(summary.caseName)) {
            rows.push({
                caseName: summary.caseName,
                right: summary,
            });
        }
    }

    return rows;
};

export const buildModelCompareRows = (
    left: EvalModelConfig[],
    right: EvalModelConfig[],
): EvalModelCompareRow[] => {
    const leftMap = new Map(left.map((entry) => [entry.role, entry]));
    const rightMap = new Map(right.map((entry) => [entry.role, entry]));
    const roles = new Set([...leftMap.keys(), ...rightMap.keys()]);
    return [...roles]
        .toSorted((leftRole, rightRole) => leftRole.localeCompare(rightRole))
        .map((role) => ({
            role,
            left: leftMap.get(role),
            right: rightMap.get(role),
        }));
};

export const formatPercentValue = (value: number | undefined): string =>
    formatPercent(value);

export const formatDeltaPercent = (value: number | undefined): string => {
    if (value === undefined) {
        return "-";
    }
    const pct = value * 100;
    const formatted = formatLocaleNumber(pct, {
        maximumFractionDigits: Number.isInteger(pct) ? 0 : 1,
    });
    const sign = pct > 0 ? "+" : "";
    return `${sign}${formatted}%`;
};

export const formatDurationValue = (value: number | undefined): string => {
    if (value === undefined) {
        return "-";
    }
    return `${formatLocaleNumber(value, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}s`;
};

export const formatDeltaDuration = (value: number | undefined): string => {
    if (value === undefined) {
        return "-";
    }
    const sign = value > 0 ? "+" : "";
    return `${sign}${formatLocaleNumber(value, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}s`;
};

export const getDeltaClassName = (
    delta: number | undefined,
    positiveIsGood: boolean,
): string => {
    if (delta === undefined || delta === 0) {
        return "text-muted-foreground";
    }
    const positiveClass = "text-emerald-600 dark:text-emerald-400";
    if (positiveIsGood) {
        return delta > 0 ? positiveClass : "text-destructive";
    }
    return delta > 0 ? "text-destructive" : positiveClass;
};

export const resolveModelDelta = (
    left: string | undefined,
    right: string | undefined,
): { label: string; className: string } => {
    if (
        left === undefined ||
        left === "" ||
        right === undefined ||
        right === ""
    ) {
        return { label: "-", className: "text-muted-foreground" };
    }
    if (left === right) {
        return { label: "Same", className: "text-muted-foreground" };
    }
    return { label: "Changed", className: "text-foreground" };
};

export const sortReportsByGenerated = (
    left: EvalReportSummary,
    right: EvalReportSummary,
): number =>
    new Date(right.generatedAt).getTime() -
    new Date(left.generatedAt).getTime();
