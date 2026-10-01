import {
    createHashHistory,
    createRootRoute,
    createRoute,
    createRouter,
    redirect,
} from "@tanstack/react-router";

import { AdoptionPage } from "../adoption/components/adoption-page";
import { InvestigatePage } from "../chat/components/chat-page";
import { AnalyticsPage } from "../chat-analytics/components/analytics-page";
import { ChatInsightsPage } from "../chat-insights/components/chat-insights-page";
import {
    ChatDetailPage,
    ChatsPage,
    InvestigationDetailPage,
    InvestigationsPage,
} from "../chats/components/chats-page";
import { validateChatsSearch } from "../chats/lib/search-state";
import {
    ComplianceFlagPage,
    ComplianceHomePage,
    ComplianceInstructionsPage,
    CompliancePage,
    ComplianceScreeningPage,
} from "../compliance/components/compliance-page";
import { validateComplianceSearch } from "../compliance/lib/presentation";
import { EvalCasesPage } from "../evals/components/eval-cases-page";
import { EvalsPage } from "../evals/components/evals-page";
import { EvalsReportsPage } from "../evals/components/evals-reports-page";
import { validateEvalCasesSearch } from "../evals/lib/case-search-state";
import { validateEvalReportsSearch } from "../evals/lib/reports-search-state";
import { FeedbackPage } from "../feedback/components/feedback-page";
import { validateFeedbackSearch } from "../feedback/lib/search-state";
import { InstructionsPage } from "../instructions/components/instructions-page";
import { MessagesPage } from "../messages/components/messages-page";
import { validateMessagesSearch } from "../messages/lib/search-state";
import { PublicAnalyticsPage } from "../public-analytics/components/public-analytics-page";
import { QualityPage } from "../quality/components/quality-page";
import { RagPage } from "../rag/components/rag-page";
import { RagJobsPage } from "../rag-jobs/components/rag-jobs-page";
import { RagViewerPage } from "../rag-viewer/components/rag-viewer-page";
import { validateRagViewerSearch } from "../rag-viewer/lib/search-state";
import { RbacPage } from "../rbac/components/rbac-page";
import { ResourcesPage } from "../resources/components/resources-page";
import { validateResourcesSearch } from "../resources/lib/search-state";
import { SettingsPage } from "../settings/components/settings-page";
import { EvalTracesPage } from "../traces/components/eval-traces-page";
import {
    EvalTraceDetailPage,
    TraceDetailPage,
} from "../traces/components/trace-detail-page";
import { TracesPage } from "../traces/components/traces-page";
import { UsagePage } from "../usage/components/usage-page";
import { ChatRoute } from "./chat-route";
import { App } from "./components/app";
import type { AppView } from "./feature-flags";

const RootRoute = createRootRoute({
    component: App,
});

const redirectToView = (view: AppView): ReturnType<typeof redirect> => {
    switch (view) {
        case "chat": {
            return redirect({
                to: "/chat",
                search: {
                    chat: undefined,
                    platform: undefined,
                    userId: undefined,
                    userEmail: undefined,
                },
            });
        }
        case "chats": {
            return redirect({
                to: "/chats",
                search: {
                    chat: undefined,
                },
            });
        }
        case "messages": {
            return redirect({
                to: "/messages",
            });
        }
        case "compliance": {
            return redirect({ to: "/compliance" });
        }
        case "feedback": {
            return redirect({
                to: "/feedback",
                search: {
                    chat: undefined,
                    message: undefined,
                },
            });
        }
        case "investigate": {
            return redirect({
                to: "/investigate",
                search: {
                    chat: undefined,
                },
            });
        }
        case "investigations": {
            return redirect({
                to: "/investigations",
                search: {
                    chat: undefined,
                },
            });
        }
        case "usage": {
            return redirect({
                to: "/usage",
            });
        }
        case "traces": {
            return redirect({
                to: "/traces",
                search: {
                    trace: undefined,
                    span: undefined,
                },
            });
        }
        case "analytics": {
            return redirect({
                to: "/analytics",
            });
        }
        case "chat-insights": {
            return redirect({
                to: "/chat-insights",
            });
        }
        case "quality": {
            return redirect({
                to: "/quality",
            });
        }
        case "adoption": {
            return redirect({
                to: "/adoption",
            });
        }
        case "public-analytics": {
            return redirect({
                to: "/public-analytics",
            });
        }
        case "evals": {
            return redirect({
                to: "/evals",
            });
        }
        case "eval-cases": {
            return redirect({
                to: "/eval-cases",
            });
        }
        case "eval-reports": {
            return redirect({
                to: "/eval-reports",
                search: {
                    report: undefined,
                },
            });
        }
        case "eval-traces": {
            return redirect({
                to: "/eval-traces",
                search: {
                    trace: undefined,
                    span: undefined,
                },
            });
        }
        case "instructions": {
            return redirect({
                to: "/instructions",
                search: {
                    tab: undefined,
                },
            });
        }
        case "rag": {
            return redirect({
                to: "/rag",
            });
        }
        case "rag-jobs": {
            return redirect({
                to: "/rag-jobs",
            });
        }
        case "rag-viewer": {
            return redirect({
                to: "/rag-viewer",
            });
        }
        case "resources": {
            return redirect({
                to: "/resources",
            });
        }
        case "rbac": {
            return redirect({
                to: "/rbac",
            });
        }
        case "settings": {
            return redirect({
                to: "/settings",
            });
        }
        default: {
            const exhaustiveCheck: never = view;
            return exhaustiveCheck;
        }
    }
};

const redirectToDefaultView = (): ReturnType<typeof redirect> =>
    redirectToView("chat");

const IndexRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/",
    beforeLoad: () => redirectToDefaultView(),
});

const ChatRouteEntry = createRoute({
    getParentRoute: () => RootRoute,
    path: "/chat",
    validateSearch: (search) => ({
        chat: typeof search.chat === "string" ? search.chat : undefined,
        platform:
            search.platform === "my" ||
            search.platform === "internal" ||
            search.platform === "public"
                ? search.platform
                : undefined,
        userId: typeof search.userId === "string" ? search.userId : undefined,
        userEmail:
            typeof search.userEmail === "string" ? search.userEmail : undefined,
    }),
    component: ChatRoute,
});

const ChatsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/chats",
    validateSearch: validateChatsSearch,
    component: ChatsPage,
});

const ChatDetailRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/chats/$chatId",
    validateSearch: (search) => ({
        message:
            typeof search.message === "string" ? search.message : undefined,
    }),
    component: ChatDetailPage,
});

const MessagesRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/messages",
    validateSearch: validateMessagesSearch,
    component: MessagesPage,
});

const ComplianceRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/compliance",
    validateSearch: () => ({}),
    component: CompliancePage,
});

const ComplianceHomeRoute = createRoute({
    getParentRoute: () => ComplianceRoute,
    path: "/",
    component: ComplianceHomePage,
});

const ComplianceInstructionsRoute = createRoute({
    getParentRoute: () => ComplianceRoute,
    path: "/instructions",
    component: ComplianceInstructionsPage,
});

const ComplianceScreeningRoute = createRoute({
    getParentRoute: () => ComplianceRoute,
    path: "/screenings/$screeningId",
    validateSearch: validateComplianceSearch,
    component: ComplianceScreeningPage,
});

const ComplianceFlagRoute = createRoute({
    getParentRoute: () => ComplianceRoute,
    path: "/screenings/$screeningId/flags/$flagId",
    validateSearch: validateComplianceSearch,
    component: ComplianceFlagPage,
});

const ComplianceRouteTree = ComplianceRoute.addChildren([
    ComplianceHomeRoute,
    ComplianceInstructionsRoute,
    ComplianceScreeningRoute,
    ComplianceFlagRoute,
]);

const FeedbackRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/feedback",
    validateSearch: validateFeedbackSearch,
    component: FeedbackPage,
});

const InvestigateRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/investigate",
    validateSearch: (search) => ({
        chat: typeof search.chat === "string" ? search.chat : undefined,
        message:
            typeof search.message === "string" ? search.message : undefined,
    }),
    component: InvestigatePage,
});

const InvestigationsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/investigations",
    validateSearch: (search) => ({
        chat: typeof search.chat === "string" ? search.chat : undefined,
    }),
    component: InvestigationsPage,
});

const InvestigationDetailRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/investigations/$chatId",
    validateSearch: (search) => ({
        message:
            typeof search.message === "string" ? search.message : undefined,
    }),
    component: InvestigationDetailPage,
});

const UsageRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/usage",
    component: UsagePage,
});

const TracesRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/traces",
    validateSearch: (search) => ({
        trace: typeof search.trace === "string" ? search.trace : undefined,
        span: typeof search.span === "string" ? search.span : undefined,
    }),
    component: TracesPage,
});

const TraceDetailRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/traces/$traceId",
    validateSearch: (search) => ({
        span: typeof search.span === "string" ? search.span : undefined,
        view:
            search.view === "span" || search.view === "summary"
                ? search.view
                : undefined,
    }),
    component: TraceDetailPage,
});

const AnalyticsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/analytics",
    component: AnalyticsPage,
});

const ChatInsightsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/chat-insights",
    component: ChatInsightsPage,
});

const QualityRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/quality",
    component: QualityPage,
});

const AdoptionRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/adoption",
    component: AdoptionPage,
});

const PublicAnalyticsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/public-analytics",
    component: PublicAnalyticsPage,
});

const EvalsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/evals",
    component: EvalsPage,
});

const EvalCasesRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/eval-cases",
    validateSearch: validateEvalCasesSearch,
    component: EvalCasesPage,
});

const EvalReportsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/eval-reports",
    validateSearch: validateEvalReportsSearch,
    component: EvalsReportsPage,
});

const EvalTracesRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/eval-traces",
    validateSearch: (search) => ({
        trace: typeof search.trace === "string" ? search.trace : undefined,
        span: typeof search.span === "string" ? search.span : undefined,
    }),
    component: EvalTracesPage,
});

const EvalTraceDetailRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/eval-traces/$traceId",
    validateSearch: (search) => ({
        span: typeof search.span === "string" ? search.span : undefined,
        view:
            search.view === "span" || search.view === "summary"
                ? search.view
                : undefined,
    }),
    component: EvalTraceDetailPage,
});

const InstructionsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/instructions",
    validateSearch: (search) => ({
        tab:
            search.tab === "editor" || search.tab === "test-chat"
                ? search.tab
                : undefined,
    }),
    component: InstructionsPage,
});

const RagRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/rag",
    component: RagPage,
});

const RagJobsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/rag-jobs",
    component: RagJobsPage,
});

const SettingsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/settings",
    component: SettingsPage,
});

const RagViewerRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/rag-viewer",
    validateSearch: validateRagViewerSearch,
    component: RagViewerPage,
});

const ResourcesRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/resources",
    validateSearch: validateResourcesSearch,
    component: ResourcesPage,
});

const RbacRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/rbac",
    component: RbacPage,
});

const routeTree = RootRoute.addChildren([
    IndexRoute,
    ChatRouteEntry,
    ChatsRoute,
    ChatDetailRoute,
    MessagesRoute,
    ComplianceRouteTree,
    FeedbackRoute,
    InvestigateRoute,
    InvestigationsRoute,
    InvestigationDetailRoute,
    UsageRoute,
    TracesRoute,
    TraceDetailRoute,
    AnalyticsRoute,
    ChatInsightsRoute,
    QualityRoute,
    AdoptionRoute,
    PublicAnalyticsRoute,
    EvalsRoute,
    EvalCasesRoute,
    EvalReportsRoute,
    EvalTracesRoute,
    EvalTraceDetailRoute,
    InstructionsRoute,
    RagRoute,
    RagJobsRoute,
    RagViewerRoute,
    ResourcesRoute,
    RbacRoute,
    SettingsRoute,
]);

export const router = createRouter({
    routeTree,
    history: createHashHistory(),
});

declare module "@tanstack/react-router" {
    interface Register {
        router: typeof router;
    }
}
