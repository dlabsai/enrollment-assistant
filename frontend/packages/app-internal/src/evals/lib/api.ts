import { isRecord } from "@va/shared/lib/type-guards";

import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type {
    EvalCaseDefinition,
    EvalCaseDefinitionApi,
    EvalCaseResult,
    EvalCaseResultApi,
    EvalCaseRunResult,
    EvalCaseRunResultApi,
    EvalEvaluationResult,
    EvalEvaluationResultApi,
    EvalReportDetail,
    EvalReportDetailApi,
    EvalReportList,
    EvalReportListApi,
    EvalReportSummary,
    EvalReportSummaryApi,
    EvalRunLogEntry,
    EvalRunReportEvent,
    EvalRunRequest,
    EvalRunSnapshot,
    EvalRunSnapshotApi,
    EvalRunStatusEvent,
    EvalSuite,
    EvalTestCasesApi,
} from "../types";
import type { EvalReportsSortBy } from "./reports-search-state";

const mapSummary = (report: EvalReportSummaryApi): EvalReportSummary => ({
    id: report.id,
    title: report.title,
    name: report.name,
    suite: report.suite,
    generatedAt: report.generated_at,
    repeats: report.repeats,
    concurrency: report.concurrency,
    passThreshold: report.pass_threshold,
    status: report.status,
    caseCount: report.case_count,
    runCount: report.run_count,
    isInternal: report.is_internal,
    modelConfigs: report.model_configs,
    passRateAverage: report.pass_rate_average ?? undefined,
    durationMedianAverage: report.duration_median_average ?? undefined,
});

const mapEvaluationResult = (
    result: EvalEvaluationResultApi,
): EvalEvaluationResult => ({
    name: result.name,
    value: result.value,
    reason: result.reason,
});

const mapEvaluationResultMap = (
    results: Record<string, EvalEvaluationResultApi>,
): Record<string, EvalEvaluationResult> =>
    Object.fromEntries(
        Object.entries(results).map(([key, value]) => [
            key,
            mapEvaluationResult(value),
        ]),
    );

const mapRun = (run: EvalCaseRunResultApi): EvalCaseRunResult => ({
    runIndex: run.run_index,
    output: run.output,
    duration: run.duration,
    error: run.error,
    otelTraceId: run.otel_trace_id,
    otelSpanId: run.otel_span_id,
    assertions: mapEvaluationResultMap(run.assertions),
    scores: mapEvaluationResultMap(run.scores),
    labels: mapEvaluationResultMap(run.labels),
});

const mapCase = (caseResult: EvalCaseResultApi): EvalCaseResult => ({
    name: caseResult.name,
    inputs: caseResult.inputs,
    expectedOutput: caseResult.expected_output,
    metadata: caseResult.metadata,
    stats: caseResult.stats,
    runs: caseResult.runs.map((run) => mapRun(run)),
});

const mapDetail = (report: EvalReportDetailApi): EvalReportDetail => ({
    ...mapSummary(report),
    config: report.config,
    additionalSettings: report.additional_settings,
    cases: report.cases.map((caseResult) => mapCase(caseResult)),
});

const mapCaseDefinition = (
    caseDefinition: EvalCaseDefinitionApi,
): EvalCaseDefinition => ({
    suite: caseDefinition.suite,
    caseId: caseDefinition.case_id,
    status: caseDefinition.status,
    active: caseDefinition.active,
    payload: caseDefinition.payload,
    payloadHash: caseDefinition.payload_hash,
    canonicalPayload: caseDefinition.canonical_payload,
    diskHash: caseDefinition.disk_hash,
    overlayBaseDiskHash: caseDefinition.overlay_base_disk_hash,
    hasDiskChanges: caseDefinition.has_disk_changes,
    createdAt: caseDefinition.created_at,
    updatedAt: caseDefinition.updated_at,
});

const mapRunSnapshot = (snapshot: EvalRunSnapshotApi): EvalRunSnapshot => ({
    runId: snapshot.run_id,
    suite: snapshot.suite,
    status: snapshot.status,
    reportId: snapshot.report_id,
    errorMessage: snapshot.error_message,
    startedAt: snapshot.started_at,
    completedAt: snapshot.completed_at,
});

interface EvalRunStreamCallbacks {
    onLog: (entry: EvalRunLogEntry) => void;
    onStatus: (status: EvalRunStatusEvent) => void;
    onReport: (report: EvalRunReportEvent) => void;
    onError: (message: string) => void;
}

const parseSseEvent = (
    raw: string,
): {
    event: string;
    data: string;
} => {
    let event = "message";
    const dataLines: string[] = [];

    for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) {
            event = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
            dataLines.push(line.slice("data:".length).trim());
        }
    }

    return {
        event,
        data: dataLines.join("\n"),
    };
};

const parseSsePayload = (data: string): Record<string, unknown> | undefined => {
    try {
        const parsed: unknown = JSON.parse(data);
        return isRecord(parsed) ? parsed : undefined;
    } catch {
        return undefined;
    }
};

const isEvalStatus = (value: unknown): value is EvalRunStatusEvent["status"] =>
    value === "start" ||
    value === "complete" ||
    value === "error" ||
    value === "cancelled";

interface FetchEvalReportsParams {
    descending: boolean;
    limit: number;
    offset: number;
    search: string;
    signal?: AbortSignal;
    sortBy: EvalReportsSortBy;
}

export const fetchEvalReports = async (
    api: AuthenticatedApi,
    params: FetchEvalReportsParams,
): Promise<EvalReportList> => {
    const searchParams = new URLSearchParams({
        descending: String(params.descending),
        limit: String(params.limit),
        offset: String(params.offset),
        sort_by: params.sortBy,
    });
    const trimmedSearch = params.search.trim();
    if (trimmedSearch !== "") {
        searchParams.set("search", trimmedSearch);
    }

    const response = await api.get<EvalReportListApi>(
        `/evals/reports?${searchParams.toString()}`,
        { signal: params.signal },
    );
    return {
        items: response.items.map((report) => mapSummary(report)),
        total: response.total,
    };
};

export const fetchEvalReport = async (
    api: AuthenticatedApi,
    reportId: string,
): Promise<EvalReportDetail> => {
    const response = await api.get<EvalReportDetailApi>(
        `/evals/reports/${encodeURIComponent(reportId)}`,
    );
    return mapDetail(response);
};

export const fetchEvalTestCases = async (
    api: AuthenticatedApi,
    suite: EvalSuite,
): Promise<string[]> => {
    const response = await api.get<EvalTestCasesApi>(
        `/evals/test-cases?suite=${encodeURIComponent(suite)}`,
    );
    return response.cases;
};

export const fetchEvalCaseDefinitions = async (
    api: AuthenticatedApi,
    suite: EvalSuite,
): Promise<EvalCaseDefinition[]> => {
    const response = await api.get<EvalCaseDefinitionApi[]>(
        `/evals/cases?suite=${encodeURIComponent(suite)}`,
    );
    return response.map((caseDefinition) => mapCaseDefinition(caseDefinition));
};

export const createEvalCaseDefinition = async (
    api: AuthenticatedApi,
    suite: EvalSuite,
    payload: Record<string, unknown>,
): Promise<EvalCaseDefinition> => {
    const response = await api.post<EvalCaseDefinitionApi>("/evals/cases", {
        suite,
        payload,
    });
    return mapCaseDefinition(response);
};

export const updateEvalCaseDefinition = async (
    api: AuthenticatedApi,
    suite: EvalSuite,
    caseId: string,
    payload: Record<string, unknown>,
): Promise<EvalCaseDefinition> => {
    const response = await api.put<EvalCaseDefinitionApi>(
        `/evals/cases/${encodeURIComponent(caseId)}`,
        {
            suite,
            payload,
        },
    );
    return mapCaseDefinition(response);
};

export const deleteEvalCaseDefinition = async (
    api: AuthenticatedApi,
    suite: EvalSuite,
    caseId: string,
): Promise<void> => {
    await api.delete(
        `/evals/cases/${encodeURIComponent(caseId)}?suite=${encodeURIComponent(suite)}`,
    );
};

export const fetchInternalModels = async (
    api: AuthenticatedApi,
): Promise<string[]> => api.get<string[]>("/models");

export const fetchCurrentEvalRun = async (
    api: AuthenticatedApi,
): Promise<EvalRunSnapshot | null> => {
    const response = await api.get<EvalRunSnapshotApi | null>(
        "/evals/runs/current",
    );
    return response === null ? null : mapRunSnapshot(response);
};

export const cancelEvalRun = async (
    api: AuthenticatedApi,
    runId: string,
): Promise<EvalRunSnapshot> => {
    const response = await api.post<EvalRunSnapshotApi>(
        `/evals/runs/${encodeURIComponent(runId)}/cancel`,
        {},
    );
    return mapRunSnapshot(response);
};

const readEvalStream = async (
    response: Response,
    callbacks: EvalRunStreamCallbacks,
): Promise<void> => {
    const reader = response.body?.getReader();

    if (reader === undefined) {
        throw new Error("Missing streaming response body");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        // eslint-disable-next-line no-await-in-loop
        const { value, done } = await reader.read();
        if (done) {
            break;
        }
        buffer += decoder.decode(value, { stream: true });
        buffer = buffer.replaceAll("\r\n", "\n");

        let splitIndex = buffer.indexOf("\n\n");
        while (splitIndex !== -1) {
            const rawEvent = buffer.slice(0, splitIndex).trim();
            buffer = buffer.slice(splitIndex + 2);
            splitIndex = buffer.indexOf("\n\n");

            if (rawEvent !== "") {
                const parsed = parseSseEvent(rawEvent);
                if (parsed.data !== "") {
                    const payload = parseSsePayload(parsed.data);
                    if (payload !== undefined) {
                        switch (parsed.event) {
                            case "log": {
                                const { message } = payload;
                                if (typeof message === "string") {
                                    callbacks.onLog({ message });
                                }
                                break;
                            }
                            case "status": {
                                const { status: statusValue, run_id: runId } =
                                    payload;
                                if (isEvalStatus(statusValue)) {
                                    callbacks.onStatus({
                                        status: statusValue,
                                        runId:
                                            typeof runId === "string"
                                                ? runId
                                                : undefined,
                                    });
                                }
                                break;
                            }
                            case "report": {
                                const {
                                    report_id: reportId,
                                    name,
                                    generated_at: generatedAt,
                                    repeats,
                                    concurrency,
                                    run_id: runId,
                                } = payload;
                                if (
                                    typeof reportId === "string" &&
                                    typeof name === "string" &&
                                    typeof generatedAt === "string"
                                ) {
                                    callbacks.onReport({
                                        reportId,
                                        name,
                                        generatedAt,
                                        repeats:
                                            typeof repeats === "number"
                                                ? repeats
                                                : undefined,
                                        concurrency:
                                            typeof concurrency === "number"
                                                ? concurrency
                                                : undefined,
                                        runId:
                                            typeof runId === "string"
                                                ? runId
                                                : undefined,
                                    });
                                }
                                break;
                            }
                            case "error": {
                                const { message } = payload;
                                if (typeof message === "string") {
                                    callbacks.onError(message);
                                }
                                break;
                            }
                            default: {
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
};

export const runEvalStream = async (
    api: AuthenticatedApi,
    request: EvalRunRequest,
    callbacks: EvalRunStreamCallbacks,
    signal?: AbortSignal,
): Promise<void> => {
    const response = await api.postStream(
        "/evals/runs/stream",
        {
            suite: request.suite,
            repeat: request.repeat,
            max_concurrency: request.maxConcurrency,
            pass_threshold: request.passThreshold,
            test_cases: request.testCases,
            chatbot_model: request.chatbotModel,
            guardrail_model: request.guardrailModel,
            evaluation_model: request.evaluationModel,
        },
        { signal },
    );

    await readEvalStream(response, callbacks);
};

export const streamExistingEvalRun = async (
    api: AuthenticatedApi,
    runId: string,
    callbacks: EvalRunStreamCallbacks,
    signal?: AbortSignal,
): Promise<void> => {
    const response = await api.postStream(
        `/evals/runs/${encodeURIComponent(runId)}/stream`,
        {},
        { signal },
    );
    await readEvalStream(response, callbacks);
};
