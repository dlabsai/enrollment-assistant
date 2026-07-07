import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type {
    TraceDetail,
    TracePlatformFilter,
    TraceSummaryPage,
} from "../types";

interface FetchTraceIndexParams {
    aiOnly: boolean;
    limit: number;
    offset: number;
    platform: TracePlatformFilter;
    start?: string;
    end?: string;
    source?: "runtime" | "evals";
}

export const fetchTraceIndex = async (
    api: AuthenticatedApi,
    params: FetchTraceIndexParams,
): Promise<TraceSummaryPage> => {
    const queryParams = new URLSearchParams({
        limit: String(params.limit),
        offset: String(params.offset),
        sort_by: "latest_start",
        descending: "true",
    });
    if (params.aiOnly) {
        queryParams.set("ai_only", "true");
    }
    if (params.platform !== "both") {
        queryParams.set("platform", params.platform);
    }
    if (params.start !== undefined) {
        queryParams.set("start", params.start);
    }
    if (params.end !== undefined) {
        queryParams.set("end", params.end);
    }
    const pathPrefix = params.source === "evals" ? "/evals" : "/usage";
    const query = queryParams.toString();
    const path = query
        ? `${pathPrefix}/trace-index?${query}`
        : `${pathPrefix}/trace-index`;
    return api.get<TraceSummaryPage>(path);
};

export const fetchTraceDetail = async (
    api: AuthenticatedApi,
    traceId: string,
    source: "runtime" | "evals" = "runtime",
): Promise<TraceDetail> => {
    const pathPrefix = source === "evals" ? "/evals" : "/usage";
    return api.get<TraceDetail>(`${pathPrefix}/trace/${traceId}`);
};

export const fetchTraceDetailByMessageId = async (
    api: AuthenticatedApi,
    messageId: string,
    source: "page" | "chat_trace" | "chat_activity" | "chats_trace" = "page",
): Promise<TraceDetail> =>
    api.get<TraceDetail>(
        `/usage/trace-by-message/${messageId}?source=${source}`,
    );
