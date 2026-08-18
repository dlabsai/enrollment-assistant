import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    readRagOperationStream,
    type RagOperationLogEntry,
    type RagOperationProgressEvent,
    type RagOperationStatusEvent,
    type RagOperationStreamCallbacks,
} from "../src/rag/lib/operation-stream.ts";

const emptyCallbacks = (): RagOperationStreamCallbacks => ({
    onError: () => undefined,
    onLog: () => undefined,
    onProgress: () => undefined,
    onStatus: () => undefined,
});

const createStreamingResponse = (chunks: string[]): Response => {
    const encoder = new TextEncoder();
    return new Response(
        new ReadableStream<Uint8Array>({
            start: (controller) => {
                for (const chunk of chunks) {
                    controller.enqueue(encoder.encode(chunk));
                }
                controller.close();
            },
        }),
    );
};

describe("readRagOperationStream", () => {
    it("decodes chunked status, log, error, and progress events", async () => {
        const logs: RagOperationLogEntry[] = [];
        const statuses: RagOperationStatusEvent[] = [];
        const errors: string[] = [];
        const progressEvents: RagOperationProgressEvent[] = [];
        const callbacks: RagOperationStreamCallbacks = {
            onError: (message) => errors.push(message),
            onLog: (entry) => logs.push(entry),
            onProgress: (progress) => progressEvents.push(progress),
            onStatus: (status) => statuses.push(status),
        };
        const body = [
            'event: status\r\ndata: {"status":"start"}\r\n\r\n',
            'event: log\r\ndata: {"stream":"stdout","message":"Working"}\r\n\r\n',
            'event: progress\r\ndata: {"steps":[{"key":"wordpress_sync","label":"WordPress sync","status":"running"}],"current_step":"wordpress_sync","finished_steps":0,"total_steps":1}\r\n\r\n',
            'event: error\r\ndata: {"message":"Failed to run RAG build"}\r\n\r\n',
            'event: status\r\ndata: {"status":"error","exit_code":1}\r\n\r\n',
        ].join("");

        await readRagOperationStream(
            createStreamingResponse([
                body.slice(0, 31),
                body.slice(31, 107),
                body.slice(107),
            ]),
            callbacks,
        );

        assert.deepEqual(logs, [{ stream: "stdout", message: "Working" }]);
        assert.deepEqual(statuses, [
            { status: "start", exitCode: undefined },
            { status: "error", exitCode: 1 },
        ]);
        assert.deepEqual(errors, ["Failed to run RAG build"]);
        assert.deepEqual(progressEvents, [
            {
                steps: [
                    {
                        key: "wordpress_sync",
                        label: "WordPress sync",
                        status: "running",
                    },
                ],
                currentStep: "wordpress_sync",
                finishedSteps: 0,
                totalSteps: 1,
            },
        ]);
    });

    it("rejects a response without a streaming body", async () => {
        await assert.rejects(
            readRagOperationStream(new Response(null), emptyCallbacks()),
            /Missing streaming response body/u,
        );
    });
});
