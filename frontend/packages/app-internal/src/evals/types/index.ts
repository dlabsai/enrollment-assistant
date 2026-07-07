export type EvalSuite = "chatbot" | "guardrails";

export type EvalCaseStatus = "disk" | "overridden" | "deleted" | "database";

export interface EvalCaseDefinition {
    suite: EvalSuite;
    caseId: string;
    status: EvalCaseStatus;
    active: boolean;
    payload: Record<string, unknown>;
    payloadHash: string;
    canonicalPayload: Record<string, unknown> | null;
    diskHash: string | null;
    overlayBaseDiskHash: string | null;
    hasDiskChanges: boolean;
    createdAt: string | null;
    updatedAt: string | null;
}

export interface EvalCaseDefinitionApi {
    suite: EvalSuite;
    case_id: string;
    status: EvalCaseStatus;
    active: boolean;
    payload: Record<string, unknown>;
    payload_hash: string;
    canonical_payload: Record<string, unknown> | null;
    disk_hash: string | null;
    overlay_base_disk_hash: string | null;
    has_disk_changes: boolean;
    created_at: string | null;
    updated_at: string | null;
}

export interface EvalEvaluationResult {
    name: string;
    value: boolean | number | string | null;
    reason: string | null;
}

export interface EvalCaseRunResult {
    runIndex: number;
    output: unknown;
    duration: number;
    error: string | null;
    otelTraceId: string | null;
    otelSpanId: string | null;
    assertions: Record<string, EvalEvaluationResult>;
    scores: Record<string, EvalEvaluationResult>;
    labels: Record<string, EvalEvaluationResult>;
}

export interface EvalCaseResult {
    name: string;
    inputs: unknown;
    expectedOutput: unknown;
    metadata: unknown;
    stats: Record<string, unknown>;
    runs: EvalCaseRunResult[];
}

export interface EvalReportSummary {
    id: string;
    title: string;
    name: string;
    suite: string;
    generatedAt: string;
    repeats: number;
    concurrency: number;
    passThreshold: number;
    status: string;
    caseCount: number;
    runCount: number;
    isInternal: boolean | null;
    modelConfigs: Record<string, unknown>;
    passRateAverage: number | undefined;
    durationMedianAverage: number | undefined;
}

export interface EvalReportList {
    items: EvalReportSummary[];
    total: number;
}

export interface EvalReportDetail extends EvalReportSummary {
    config: Record<string, unknown>;
    additionalSettings: Record<string, unknown>;
    cases: EvalCaseResult[];
}

export interface EvalRunRequest {
    suite: EvalSuite;
    repeat: number;
    maxConcurrency: number;
    passThreshold: number;
    testCases?: string;
    chatbotModel?: string;
    guardrailModel?: string;
    evaluationModel?: string;
}

export interface EvalRunLogEntry {
    message: string;
}

export interface EvalRunStatusEvent {
    status: "start" | "complete" | "error" | "cancelled";
    runId?: string;
}

export interface EvalRunReportEvent {
    reportId: string;
    name: string;
    generatedAt: string;
    repeats: number | undefined;
    concurrency: number | undefined;
    runId?: string;
}

export interface EvalRunSnapshot {
    runId: string;
    suite: EvalSuite;
    status: EvalRunStatusEvent["status"];
    reportId: string | null;
    errorMessage: string | null;
    startedAt: string;
    completedAt: string | null;
}

export interface EvalRunSnapshotApi {
    run_id: string;
    suite: EvalSuite;
    status: EvalRunStatusEvent["status"];
    report_id: string | null;
    error_message: string | null;
    started_at: string;
    completed_at: string | null;
}

export interface EvalEvaluationResultApi {
    name: string;
    value: boolean | number | string | null;
    reason: string | null;
}

export interface EvalCaseRunResultApi {
    run_index: number;
    output: unknown;
    duration: number;
    error: string | null;
    otel_trace_id: string | null;
    otel_span_id: string | null;
    assertions: Record<string, EvalEvaluationResultApi>;
    scores: Record<string, EvalEvaluationResultApi>;
    labels: Record<string, EvalEvaluationResultApi>;
}

export interface EvalCaseResultApi {
    name: string;
    inputs: unknown;
    expected_output: unknown;
    metadata: unknown;
    stats: Record<string, unknown>;
    runs: EvalCaseRunResultApi[];
}

export interface EvalReportSummaryApi {
    id: string;
    title: string;
    name: string;
    suite: string;
    generated_at: string;
    repeats: number;
    concurrency: number;
    pass_threshold: number;
    status: string;
    case_count: number;
    run_count: number;
    is_internal: boolean | null;
    model_configs: Record<string, unknown>;
    pass_rate_average: number | null;
    duration_median_average: number | null;
}

export interface EvalReportListApi {
    items: EvalReportSummaryApi[];
    total: number;
}

export interface EvalReportDetailApi extends EvalReportSummaryApi {
    config: Record<string, unknown>;
    additional_settings: Record<string, unknown>;
    cases: EvalCaseResultApi[];
}

export interface EvalTestCasesApi {
    suite: EvalSuite;
    cases: string[];
}
