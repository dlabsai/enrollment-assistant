import { Alert, AlertDescription, AlertTitle } from "@va/shared/components/ui/alert";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import { Spinner } from "@va/shared/components/ui/spinner";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "@va/shared/components/ui/tabs";
import { CircleAlert, Filter, Play, RefreshCw } from "lucide-react";
import { type JSX, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { hasPermission } from "../../auth/lib/permissions";
import { PageHeader, PageHeaderGroup } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { LoadingState, PageError } from "../../components/page-state";
import { TimeRangeFilter } from "../../components/time-range-filter";
import { formatTableTimestamp } from "../../lib/date-format";
import { usePersistedTimeRange } from "../../lib/hooks/use-persisted-time-range";
import { useChatInsightsData } from "../hooks/use-chat-insights-data";
import { runChatInsightAnalysis } from "../lib/api";
import { CategoriesPanel } from "./categories-panel";
import { ChatInsightsHelp } from "./chat-insights-help";
import { InsightSummaryCards } from "./insight-summary-cards";
import { SourcesPanel } from "./sources-panel";
import { TopicsPanel } from "./topics-panel";
import { TrendMatrix } from "./trend-matrix";

const activeStatuses = new Set(["queued", "running"]);
const chatInsightsFilterStorageKey = "internal-chat-insights-filters";

const statusLabel = (value: string): string => {
    switch (value) {
        case "queued": {
            return "Queued";
        }
        case "running": {
            return "Running";
        }
        case "completed": {
            return "Completed";
        }
        case "completed_with_errors": {
            return "Completed with errors";
        }
        case "completed_with_warnings": {
            return "Completed with warnings";
        }
        case "failed": {
            return "Failed";
        }
        default: {
            return value;
        }
    }
};

const statusVariant = (
    value: string,
): "default" | "secondary" | "destructive" | "outline" => {
    if (value === "failed" || value === "completed_with_errors") {
        return "destructive";
    }
    if (value === "completed" || value === "completed_with_warnings") {
        return "secondary";
    }
    return activeStatuses.has(value) ? "default" : "outline";
};

export const ChatInsightsPage = (): JSX.Element => {
    const { user } = useAuth();
    const api = useAuthenticatedApi();
    const {
        timeRange,
        customRange,
        setTimeRange,
        setCustomRange,
        resetTimeRange,
    } = usePersistedTimeRange(chatInsightsFilterStorageKey, "90d");
    const [startingRun, setStartingRun] = useState(false);
    const { data, loading, hasLoaded, error, refresh } = useChatInsightsData(
        timeRange,
        customRange,
    );
    const latestRun = data?.summary.latest_run;
    const runActive = activeStatuses.has(latestRun?.status ?? "");
    const canRun = hasPermission(user, "run_chat_insights");
    const canManage = hasPermission(
        user,
        "manage_chat_insight_categories",
    );

    const startRun = async (): Promise<void> => {
        setStartingRun(true);
        try {
            const run = await runChatInsightAnalysis(api);
            toast.success(
                run.created
                    ? "Analysis queued"
                    : "An analysis run is already active",
            );
            refresh();
        } catch (runError) {
            toast.error(
                runError instanceof Error && runError.message !== ""
                    ? runError.message
                    : "Failed to start analysis",
            );
        } finally {
            setStartingRun(false);
        }
    };

    if (loading && !hasLoaded) {
        return <LoadingState />;
    }
    if (error !== undefined || data === undefined) {
        return (
            <PageError
                message={error ?? "Failed to load chat topics and sources."}
                onRetry={refresh}
            />
        );
    }

    return (
        <PageShell variant="dashboard">
            <PageHeader
                title="Chat Topics & Sources"
                titleAddon={
                    <>
                        <ChatInsightsHelp />
                        {latestRun !== undefined && latestRun !== null && (
                            <Badge variant={statusVariant(latestRun.status)}>
                                {statusLabel(latestRun.status)}
                            </Badge>
                        )}
                    </>
                }
            >
                <span className="text-muted-foreground text-xs tabular-nums">
                    {data.summary.data_through === null
                        ? "No published analysis"
                        : `Data through ${formatTableTimestamp(data.summary.data_through)}`}
                </span>
                <PageHeaderGroup>
                    <TimeRangeFilter
                        customRange={customRange}
                        onChange={setTimeRange}
                        onCustomRangeChange={setCustomRange}
                        value={timeRange}
                    />
                </PageHeaderGroup>
                <Button
                    onClick={resetTimeRange}
                    variant="outline"
                >
                    <Filter data-icon="inline-start" />
                    Clear
                </Button>
                <Button
                    disabled={loading}
                    onClick={refresh}
                    variant="outline"
                >
                    <RefreshCw data-icon="inline-start" />
                    Refresh
                </Button>
                {canRun && (
                    <Button
                        disabled={runActive || startingRun}
                        onClick={() => {
                            void startRun();
                        }}
                    >
                        {startingRun || runActive ? (
                            <Spinner data-icon="inline-start" />
                        ) : (
                            <Play data-icon="inline-start" />
                        )}
                        {runActive ? "Analysis running" : "Run analysis"}
                    </Button>
                )}
            </PageHeader>

            {(latestRun?.status === "failed" ||
                latestRun?.status === "completed_with_errors" ||
                latestRun?.status === "completed_with_warnings") && (
                <PageSection>
                    <Alert
                        variant={
                            latestRun.status === "completed_with_warnings"
                                ? "default"
                                : "destructive"
                        }
                    >
                        <CircleAlert />
                        <AlertTitle>{statusLabel(latestRun.status)}</AlertTitle>
                        <AlertDescription>
                            {latestRun.error_count > 0
                                ? `${latestRun.error_count} analysis batches did not complete. Previous results remain available where possible.`
                                : "The latest quality check was below its required consistency level. Existing labels were kept."}
                        </AlertDescription>
                    </Alert>
                </PageSection>
            )}

            <PageSection>
                <InsightSummaryCards
                    coverage={data.summary.coverage}
                    currentDocumentsUsed={data.summary.sources.reduce(
                        (total, source) =>
                            total + source.current_documents_used,
                        0,
                    )}
                />
            </PageSection>

            <PageSection>
                <Tabs defaultValue="topics">
                    <TabsList>
                        <TabsTrigger value="topics">Topics</TabsTrigger>
                        <TabsTrigger value="sources">
                            Documents & Sources
                        </TabsTrigger>
                        <TabsTrigger value="trends">Trends</TabsTrigger>
                        <TabsTrigger value="categories">
                            Topic definitions
                        </TabsTrigger>
                    </TabsList>
                    <TabsContent className="mt-4" value="topics">
                        <TopicsPanel
                            pairs={data.summary.topic_pairs}
                            requestTypes={data.summary.request_types}
                            topics={data.summary.topics}
                        />
                    </TabsContent>
                    <TabsContent className="mt-4" value="sources">
                        <SourcesPanel
                            documents={data.summary.top_documents}
                            sources={data.summary.sources}
                        />
                    </TabsContent>
                    <TabsContent className="mt-4" value="trends">
                        <TrendMatrix
                            documentRows={data.summary.document_trends}
                            granularity={data.summary.time_granularity}
                            sourceRows={data.summary.source_trends}
                            topicRows={data.summary.topic_trends}
                        />
                    </TabsContent>
                    <TabsContent className="mt-4" value="categories">
                        <CategoriesPanel
                            canManage={canManage}
                            categoryList={data.categories}
                            onChanged={refresh}
                        />
                    </TabsContent>
                </Tabs>
            </PageSection>
        </PageShell>
    );
};
