import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type RagOperationStreamCallbacks,
    readRagOperationStream,
} from "./operation-stream";

export type {
    RagOperationLogEntry,
    RagOperationProgressEvent,
    RagOperationProgressStepStatus,
    RagOperationStatusEvent,
} from "./operation-stream";

interface RagBuildCancelResult {
    status: "cancelling" | "cancelled";
}

interface RagBuildStreamOptions {
    signal?: AbortSignal;
    forceRebuild?: boolean;
    resumeExisting?: boolean;
}

export const syncEvalRagStream = async (
    api: AuthenticatedApi,
    callbacks: RagOperationStreamCallbacks,
    signal?: AbortSignal,
): Promise<void> => {
    const response = await api.postStream(
        "/rag/eval-rag/copy/stream",
        {},
        { signal },
    );

    await readRagOperationStream(response, callbacks);
};

export const runRagBuildStream = async (
    api: AuthenticatedApi,
    callbacks: RagOperationStreamCallbacks,
    options?: RagBuildStreamOptions,
): Promise<void> => {
    const response = await api.postStream(
        "/rag/build/stream",
        {
            force_rebuild: options?.forceRebuild === true,
            resume_existing: options?.resumeExisting === true,
        },
        { signal: options?.signal },
    );

    await readRagOperationStream(response, callbacks);
};

export const cancelRagBuild = async (
    api: AuthenticatedApi,
): Promise<RagBuildCancelResult> => {
    const response = await api.post<RagBuildCancelResult>(
        "/rag/build/cancel",
        {},
    );
    return { status: response.status };
};
