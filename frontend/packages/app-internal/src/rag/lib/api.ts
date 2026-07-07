import { isRecord } from "@va/shared/lib/type-guards";

import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";

export interface RagOperationLogEntry {
    stream: "stdout" | "stderr" | "command";
    message: string;
}

export interface RagOperationStatusEvent {
    status: "start" | "complete" | "error" | "cancelled";
    exitCode?: number;
}

export type RagOperationProgressStepStatus =
    | "pending"
    | "running"
    | "completed"
    | "skipped"
    | "error";

export interface RagOperationProgressStep {
    key: string;
    label: string;
    status: RagOperationProgressStepStatus;
}

export interface RagOperationProgressEvent {
    steps: RagOperationProgressStep[];
    currentStep?: string;
    finishedSteps: number;
    totalSteps: number;
}

interface RagOperationStreamCallbacks {
    onLog: (entry: RagOperationLogEntry) => void;
    onStatus: (status: RagOperationStatusEvent) => void;
    onError: (message: string) => void;
    onProgress: (progress: RagOperationProgressEvent) => void;
}

interface RagBuildStreamOptions {
    signal?: AbortSignal;
    forceRebuild?: boolean;
    resumeExisting?: boolean;
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

const isRagOperationStatus = (
    value: unknown,
): value is RagOperationStatusEvent["status"] =>
    value === "start" ||
    value === "complete" ||
    value === "error" ||
    value === "cancelled";

const isRagOperationProgressStepStatus = (
    value: unknown,
): value is RagOperationProgressStepStatus =>
    value === "pending" ||
    value === "running" ||
    value === "completed" ||
    value === "skipped" ||
    value === "error";

const readRagOperationStream = async (
    response: Response,
    callbacks: RagOperationStreamCallbacks,
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
                                const { message, stream } = payload;
                                if (
                                    (stream === "stdout" ||
                                        stream === "stderr" ||
                                        stream === "command") &&
                                    typeof message === "string"
                                ) {
                                    callbacks.onLog({ message, stream });
                                }
                                break;
                            }
                            case "status": {
                                const {
                                    status: statusValue,
                                    exit_code: exitCode,
                                } = payload;
                                if (isRagOperationStatus(statusValue)) {
                                    callbacks.onStatus({
                                        status: statusValue,
                                        exitCode:
                                            typeof exitCode === "number"
                                                ? exitCode
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
                            case "progress": {
                                const {
                                    current_step: currentStep,
                                    finished_steps: finishedSteps,
                                    total_steps: totalSteps,
                                    steps,
                                } = payload;

                                if (
                                    Array.isArray(steps) &&
                                    typeof finishedSteps === "number" &&
                                    typeof totalSteps === "number"
                                ) {
                                    const parsedSteps = steps
                                        .map(
                                            (
                                                step,
                                            ):
                                                | RagOperationProgressStep
                                                | undefined => {
                                                if (!isRecord(step)) {
                                                    return undefined;
                                                }

                                                const { key, label, status } =
                                                    step;
                                                if (
                                                    typeof key === "string" &&
                                                    typeof label === "string" &&
                                                    isRagOperationProgressStepStatus(
                                                        status,
                                                    )
                                                ) {
                                                    return {
                                                        key,
                                                        label,
                                                        status,
                                                    };
                                                }

                                                return undefined;
                                            },
                                        )
                                        .filter(
                                            (
                                                step,
                                            ): step is RagOperationProgressStep =>
                                                step !== undefined,
                                        );

                                    if (parsedSteps.length === steps.length) {
                                        callbacks.onProgress({
                                            steps: parsedSteps,
                                            currentStep:
                                                typeof currentStep === "string"
                                                    ? currentStep
                                                    : undefined,
                                            finishedSteps,
                                            totalSteps,
                                        });
                                    }
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
