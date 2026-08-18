export interface RagOperationLogEntry {
    stream: "stdout" | "stderr" | "command";
    message: string;
}

export interface RagOperationStatusEvent {
    status: "start" | "cancelling" | "complete" | "error" | "cancelled";
    exitCode?: number;
}

export type RagOperationProgressStepStatus =
    "pending" | "running" | "completed" | "skipped" | "error";

interface RagOperationProgressStep {
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

export interface RagOperationStreamCallbacks {
    onLog: (entry: RagOperationLogEntry) => void;
    onStatus: (status: RagOperationStatusEvent) => void;
    onError: (message: string) => void;
    onProgress: (progress: RagOperationProgressEvent) => void;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

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
    value === "cancelling" ||
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

const dispatchSseEvent = (
    rawEvent: string,
    callbacks: RagOperationStreamCallbacks,
): void => {
    const parsed = parseSseEvent(rawEvent);
    if (parsed.data === "") {
        return;
    }

    const payload = parseSsePayload(parsed.data);
    if (payload === undefined) {
        return;
    }

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
            const { status: statusValue, exit_code: exitCode } = payload;
            if (isRagOperationStatus(statusValue)) {
                callbacks.onStatus({
                    status: statusValue,
                    exitCode:
                        typeof exitCode === "number" ? exitCode : undefined,
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
                !Array.isArray(steps) ||
                typeof finishedSteps !== "number" ||
                typeof totalSteps !== "number"
            ) {
                break;
            }

            const parsedSteps: RagOperationProgressStep[] = [];
            for (const step of steps) {
                if (!isRecord(step)) {
                    return;
                }

                const { key, label, status } = step;
                if (
                    typeof key !== "string" ||
                    typeof label !== "string" ||
                    !isRagOperationProgressStepStatus(status)
                ) {
                    return;
                }
                parsedSteps.push({ key, label, status });
            }

            callbacks.onProgress({
                steps: parsedSteps,
                currentStep:
                    typeof currentStep === "string" ? currentStep : undefined,
                finishedSteps,
                totalSteps,
            });
            break;
        }
        default: {
            break;
        }
    }
};

export const readRagOperationStream = async (
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
                dispatchSseEvent(rawEvent, callbacks);
            }
        }
    }
};
