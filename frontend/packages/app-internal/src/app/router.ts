import {
    createHashHistory,
    createRootRoute,
    createRoute,
    createRouter,
    redirect,
} from "@tanstack/react-router";

import { InvestigatePage } from "../chat/components/chat-page";
import { AnalyticsPage } from "../chat-analytics/components/analytics-page";
import {
    ChatDetailPage,
    ChatsPage,
    InvestigationDetailPage,
    InvestigationsPage,
} from "../chats/components/chats-page";
import { EvalCasesPage } from "../evals/components/eval-cases-page";
import { EvalsPage } from "../evals/components/evals-page";
import { EvalsReportsPage } from "../evals/components/evals-reports-page";
import { validateEvalCasesSearch } from "../evals/lib/case-search-state";
import { validateEvalReportsSearch } from "../evals/lib/reports-search-state";
import { FeedbackPage } from "../feedback/components/feedback-page";
import { InstructionsPage } from "../instructions/components/instructions-page";
import { MessagesPage } from "../messages/components/messages-page";
import { PublicAnalyticsPage } from "../public-analytics/components/public-analytics-page";
import { RagPage } from "../rag/components/rag-page";
import { RagExclusionsPage } from "../rag-exclusions/components/rag-exclusions-page";
import { validateRagExclusionsSearch } from "../rag-exclusions/lib/search-state";
import { RagJobsPage } from "../rag-jobs/components/rag-jobs-page";
import { RagViewerPage } from "../rag-viewer/components/rag-viewer-page";
import { validateRagViewerSearch } from "../rag-viewer/lib/search-state";
import { RbacPage } from "../rbac/components/rbac-page";
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
        case "rag-exclusions": {
            return redirect({
                to: "/rag-exclusions",
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
    validateSearch: (search) => ({
        chat: typeof search.chat === "string" ? search.chat : undefined,
    }),
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
    component: MessagesPage,
});

const FeedbackRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/feedback",
    validateSearch: (search) => ({
        chat: typeof search.chat === "string" ? search.chat : undefined,
        message:
            typeof search.message === "string" ? search.message : undefined,
    }),
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

const RagExclusionsRoute = createRoute({
    getParentRoute: () => RootRoute,
    path: "/rag-exclusions",
    validateSearch: validateRagExclusionsSearch,
    component: RagExclusionsPage,
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
    FeedbackRoute,
    InvestigateRoute,
    InvestigationsRoute,
    InvestigationDetailRoute,
    UsageRoute,
    TracesRoute,
    TraceDetailRoute,
    AnalyticsRoute,
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
    RagExclusionsRoute,
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
