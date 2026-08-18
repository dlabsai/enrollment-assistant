import { useCallback } from "react";

import { fetchTraceDetailByMessageId } from "../lib/api";
import type { TraceDetail } from "../types";
import { useTraceDetailLoader } from "./use-trace-detail-loader";

interface UseTraceDetailByMessageResult {
    detail: TraceDetail | undefined;
    loading: boolean;
    error: string | undefined;
    refresh: () => void;
}

export const useTraceDetailByMessage = (
    messageId: string | undefined,
    source: "page" | "chat_trace" | "chat_activity" | "chats_trace" = "page",
): UseTraceDetailByMessageResult => {
    const fetchByMessage = useCallback(
        async (
            api: Parameters<typeof fetchTraceDetailByMessageId>[0],
            nextMessageId: string,
            signal: AbortSignal,
        ) => fetchTraceDetailByMessageId(api, nextMessageId, source, signal),
        [source],
    );

    return useTraceDetailLoader(messageId, fetchByMessage, {
        clearDetailOnError: true,
    });
};
