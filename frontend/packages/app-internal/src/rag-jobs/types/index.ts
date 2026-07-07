export interface RagBuildJobUser {
    id: string;
    email: string;
    name: string;
}

export interface RagBuildJobSummary {
    id: string;
    jobName: string;
    trigger: string;
    status: string;
    forceRebuild: boolean;
    startedBy?: RagBuildJobUser;
    startedAt: string;
    finishedAt?: string;
    durationMs?: number;
    currentStep?: string;
    errorMessage?: string;
    totalNew: number;
    totalChanged: number;
    totalDeleted: number;
    totalUnchanged: number;
    totalSourceDocuments: number;
    totalExistingDocuments: number;
}

export interface RagBuildJobStep {
    stepKey: string;
    label: string;
    status: string;
    startedAt?: string;
    finishedAt?: string;
}

export interface RagBuildJobSourceStat {
    sourceName: string;
    documentType: string;
    newCount: number;
    changedCount: number;
    deletedCount: number;
    unchangedCount: number;
    sourceDocumentCount: number;
    existingDocumentCount: number;
}

export interface RagBuildJobDocumentChange {
    id: string;
    sourceName: string;
    documentType: string;
    changeType: string;
    sourceId: number;
    sourceKey?: string;
    title: string;
    url: string;
    previousTitle?: string;
    previousUrl?: string;
    sourceUpdatedAt?: string;
    previousSourceUpdatedAt?: string;
}

export interface RagBuildJobDetail extends RagBuildJobSummary {
    steps: RagBuildJobStep[];
    sourceStats: RagBuildJobSourceStat[];
    documentChanges: RagBuildJobDocumentChange[];
}

export interface RagBuildJobListResponse {
    items: RagBuildJobSummary[];
    total: number;
}
