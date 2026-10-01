import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type {
    ChatInsightCategory,
    ChatInsightCategoryInput,
    ChatInsightCategoryList,
    ChatInsightData,
    ChatInsightRun,
    ChatInsightSummary,
} from "../types";

export const fetchChatInsightData = async (
    api: AuthenticatedApi,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    signal?: AbortSignal,
): Promise<ChatInsightData> => {
    const params = new URLSearchParams(
        getTimeRangeQueryParams(timeRange, new Date(), customRange),
    );
    const [summary, categories] = await Promise.all([
        api.get<ChatInsightSummary>(
            `/chat-insights/summary?${params.toString()}`,
            { signal },
        ),
        api.get<ChatInsightCategoryList>("/chat-insights/categories", {
            signal,
        }),
    ]);
    return { summary, categories };
};

export const fetchLatestChatInsightRun = async (
    api: AuthenticatedApi,
    signal?: AbortSignal,
): Promise<ChatInsightRun | null> =>
    api.get<ChatInsightRun | null>("/chat-insights/runs/latest", { signal });

export const runChatInsightAnalysis = async (
    api: AuthenticatedApi,
): Promise<{ id: string; created: boolean; status: string }> =>
    api.post("/chat-insights/runs", {});

export const createChatInsightCategory = async (
    api: AuthenticatedApi,
    input: ChatInsightCategoryInput,
): Promise<ChatInsightCategory> =>
    api.post("/chat-insights/categories", input);

export const updateChatInsightCategory = async (
    api: AuthenticatedApi,
    key: string,
    input: ChatInsightCategoryInput & { active: boolean },
): Promise<ChatInsightCategory> =>
    api.put(`/chat-insights/categories/${encodeURIComponent(key)}`, input);
