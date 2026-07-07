import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type {
    RagBuildJobDetail,
    RagBuildJobListResponse,
    RagBuildJobSummary,
} from "../types";

interface RagBuildJobUserResponse {
    id: string;
    email: string;
    name: string;
}

interface RagBuildJobSummaryResponse {
    id: string;
    job_name: string;
    trigger: string;
    status: string;
    force_rebuild: boolean;
    started_by?: RagBuildJobUserResponse | null;
    started_at: string;
    finished_at?: string | null;
    duration_ms?: number | null;
    current_step?: string | null;
    error_message?: string | null;
    total_new: number;
    total_changed: number;
    total_deleted: number;
    total_unchanged: number;
    total_source_documents: number;
    total_existing_documents: number;
}

interface RagBuildJobStepResponse {
    step_key: string;
    label: string;
    status: string;
    started_at?: string | null;
    finished_at?: string | null;
}

interface RagBuildJobSourceStatResponse {
    source_name: string;
    document_type: string;
    new_count: number;
    changed_count: number;
    deleted_count: number;
    unchanged_count: number;
    source_document_count: number;
    existing_document_count: number;
}

interface RagBuildJobDocumentChangeResponse {
    id: string;
    source_name: string;
    document_type: string;
    change_type: string;
    source_id: number;
    source_key?: string | null;
    title: string;
    url: string;
    previous_title?: string | null;
    previous_url?: string | null;
    source_updated_at?: string | null;
    previous_source_updated_at?: string | null;
}

interface RagBuildJobDetailResponse extends RagBuildJobSummaryResponse {
    steps: RagBuildJobStepResponse[];
    source_stats: RagBuildJobSourceStatResponse[];
    document_changes: RagBuildJobDocumentChangeResponse[];
}

interface RagBuildJobListPayload {
    items: RagBuildJobSummaryResponse[];
    total: number;
}

const mapJobSummary = (
    item: RagBuildJobSummaryResponse,
): RagBuildJobSummary => ({
    id: item.id,
    jobName: item.job_name,
    trigger: item.trigger,
    status: item.status,
    forceRebuild: item.force_rebuild,
    startedBy: item.started_by ?? undefined,
    startedAt: item.started_at,
    finishedAt: item.finished_at ?? undefined,
    durationMs: item.duration_ms ?? undefined,
    currentStep: item.current_step ?? undefined,
    errorMessage: item.error_message ?? undefined,
    totalNew: item.total_new,
    totalChanged: item.total_changed,
    totalDeleted: item.total_deleted,
    totalUnchanged: item.total_unchanged,
    totalSourceDocuments: item.total_source_documents,
    totalExistingDocuments: item.total_existing_documents,
});

const mapJobDetail = (item: RagBuildJobDetailResponse): RagBuildJobDetail => ({
    ...mapJobSummary(item),
    steps: item.steps.map((step) => ({
        stepKey: step.step_key,
        label: step.label,
        status: step.status,
        startedAt: step.started_at ?? undefined,
        finishedAt: step.finished_at ?? undefined,
    })),
    sourceStats: item.source_stats.map((stat) => ({
        sourceName: stat.source_name,
        documentType: stat.document_type,
        newCount: stat.new_count,
        changedCount: stat.changed_count,
        deletedCount: stat.deleted_count,
        unchangedCount: stat.unchanged_count,
        sourceDocumentCount: stat.source_document_count,
        existingDocumentCount: stat.existing_document_count,
    })),
    documentChanges: item.document_changes.map((change) => ({
        id: change.id,
        sourceName: change.source_name,
        documentType: change.document_type,
        changeType: change.change_type,
        sourceId: change.source_id,
        sourceKey: change.source_key ?? undefined,
        title: change.title,
        url: change.url,
        previousTitle: change.previous_title ?? undefined,
        previousUrl: change.previous_url ?? undefined,
        sourceUpdatedAt: change.source_updated_at ?? undefined,
        previousSourceUpdatedAt: change.previous_source_updated_at ?? undefined,
    })),
});

export const fetchRagBuildJobs = async (
    api: AuthenticatedApi,
    params: {
        limit: number;
        offset: number;
        status?: string;
        trigger?: string;
        sortBy?: string;
        descending?: boolean;
    },
): Promise<RagBuildJobListResponse> => {
    const query = new URLSearchParams();
    query.set("limit", String(params.limit));
    query.set("offset", String(params.offset));
    if (params.status !== undefined && params.status !== "all") {
        query.set("status", params.status);
    }
    if (params.trigger !== undefined && params.trigger !== "all") {
        query.set("trigger", params.trigger);
    }
    if (params.sortBy !== undefined) {
        query.set("sort_by", params.sortBy);
    }
    if (params.descending !== undefined) {
        query.set("descending", String(params.descending));
    }

    const response = await api.get<RagBuildJobListPayload>(
        `/rag/jobs?${query.toString()}`,
    );
    return {
        total: response.total,
        items: response.items.map((item) => mapJobSummary(item)),
    };
};

export const fetchRagBuildJob = async (
    api: AuthenticatedApi,
    jobId: string,
): Promise<RagBuildJobDetail> =>
    mapJobDetail(
        await api.get<RagBuildJobDetailResponse>(
            `/rag/jobs/${encodeURIComponent(jobId)}`,
        ),
    );
