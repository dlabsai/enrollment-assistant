import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { createServer, type ViteDevServer } from "vite";

import type { AuthenticatedApi } from "../src/auth/hooks/use-authenticated-api.ts";
type SendMessageStream = typeof import("../src/chat/lib/api.ts").sendMessageStream;

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const sharedRoot = fileURLToPath(new URL("../../shared/src", import.meta.url));

const assistantEvent = [
    "event: assistant_message",
    'data: {"assistant_message_id":"assistant-1","assistant_message":"Answer"}',
    "",
    "",
].join("\n");

const callbacks = () => ({
    onChatId: (): void => undefined,
    onTitleUpdate: (): void => undefined,
    onAgentStage: (): void => undefined,
    onToolCall: (): void => undefined,
    onThinking: (): void => undefined,
    onAssistantMessage: (): void => undefined,
    onGroundingSources: (): void => undefined,
    onError: (): void => undefined,
});

describe("primary message stream lifecycle", () => {
    let server: ViteDevServer;
    let sendMessageStream: SendMessageStream;

    before(async () => {
        process.env.VITE_API_URL = "/api";
        server = await createServer({
            appType: "custom",
            configFile: false,
            root: packageRoot,
            optimizeDeps: { noDiscovery: true },
            resolve: {
                alias: [{ find: "@va/shared", replacement: sharedRoot }],
            },
            server: { middlewareMode: true },
        });
        ({ sendMessageStream } = await server.ssrLoadModule(
            "/src/chat/lib/api.ts",
        ));
    });

    after(async () => {
        await server.close();
    });

    const consume = async (
        body: string,
        eventCallbacks = callbacks(),
    ): Promise<void> => {
        const api = {
            postStream: async () => new Response(body),
        } as unknown as AuthenticatedApi;
        await sendMessageStream(
            api,
            {
                userMessage: "Question",
                generationAttemptId: "attempt-1",
            },
            eventCallbacks,
        );
    };

    it("rejects EOF before an assistant or generation failure", async () => {
        await assert.rejects(
            consume('event: conversation\ndata: {"conversation_id":"chat-1"}\n\n'),
            /ended before a primary outcome/,
        );
    });

    it("rejects a second primary outcome", async () => {
        const failureEvent = [
            "event: error",
            'data: {"code":"message_generation_failed","message":"The response could not be completed.","retryable":true}',
            "",
            "",
        ].join("\n");

        await assert.rejects(
            consume(`${assistantEvent}${failureEvent}`),
            /multiple primary outcomes/,
        );
    });

    it("does not deliver a malformed assistant payload", async () => {
        let assistantCalls = 0;
        const eventCallbacks = {
            ...callbacks(),
            onAssistantMessage: (): void => {
                assistantCalls += 1;
            },
        };
        const malformedAssistant = [
            "event: assistant_message",
            'data: {"assistant_message_id":"assistant-1","assistant_message":"Answer","tool_sources_used":{}}',
            "",
            "",
        ].join("\n");

        await assert.rejects(
            consume(malformedAssistant, eventCallbacks),
            /Invalid tool_sources_used payload/,
        );
        assert.equal(assistantCalls, 0);
    });

    it("keeps the delivered assistant primary when a later grounding patch is malformed", async () => {
        let assistantCalls = 0;
        const eventCallbacks = {
            ...callbacks(),
            onAssistantMessage: (): void => {
                assistantCalls += 1;
            },
        };
        const malformedGrounding = [
            "event: grounding_sources",
            'data: {"assistant_message_id":"assistant-1","grounding_sources_used":{},"grounding_source_status":"failed"}',
            "",
            "",
        ].join("\n");

        await assert.rejects(
            consume(`${assistantEvent}${malformedGrounding}`, eventCallbacks),
            /Invalid grounding_sources_used payload/,
        );
        assert.equal(assistantCalls, 1);
    });
});
