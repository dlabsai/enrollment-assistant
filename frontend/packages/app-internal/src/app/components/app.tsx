import { Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import {
    SidebarInset,
    SidebarProvider,
} from "@va/shared/components/ui/sidebar";
import { Toaster } from "@va/shared/components/ui/sonner";
import { UNIVERSITY_NAME } from "@va/shared/config";
import { setDocumentTitle } from "@va/shared/lib/document-title";
import { logger } from "@va/shared/lib/logger";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";
import { ErrorBoundary, type FallbackProps } from "react-error-boundary";
import { toast } from "sonner";

import { AuthPage } from "../../auth/components/auth-page";
import { useAuth } from "../../auth/contexts/auth-context";
import { AuthProvider } from "../../auth/contexts/auth-provider";
import type { UserProfile } from "../../auth/types";
import { LoadingState, PageError } from "../../components/page-state";
import { ThemeProvider } from "../../lib/theme-provider";
import { type AppView, isAppView } from "../feature-flags";
import { canAccessView, getDefaultAccessibleView } from "../view-access";
import { AppSidebar } from "./app-sidebar";

const appViewTitle: Record<AppView, string> = {
    chat: "Chat",
    chats: "Chats",
    messages: "Messages",
    feedback: "Feedback",
    investigate: "Investigate",
    investigations: "Investigations",
    usage: "Usage",
    traces: "Traces",
    analytics: "Chat Analytics",
    "public-analytics": "Public Analytics",
    evals: "Eval Runner",
    "eval-cases": "Eval Cases",
    "eval-reports": "Eval Reports",
    "eval-traces": "Eval Traces",
    instructions: "Instructions",
    rag: "KB Builder",
    "rag-jobs": "KB Builder Jobs",
    "rag-viewer": "KB Viewer",
    "rag-exclusions": "KB Controls",
    rbac: "Access Controls",
    settings: "Settings",
};

const getRequestedView = (pathname: string): AppView | undefined => {
    const normalized = pathname.replace(/^\/+/u, "");
    if (normalized === "") {
        return undefined;
    }
    if (normalized.startsWith("chats/")) {
        return "chats";
    }
    if (normalized.startsWith("investigations/")) {
        return "investigations";
    }
    if (normalized.startsWith("traces/")) {
        return "traces";
    }
    if (normalized.startsWith("eval-traces/")) {
        return "eval-traces";
    }
    return isAppView(normalized) ? normalized : undefined;
};

const resolveView = (
    pathname: string,
    user: UserProfile | undefined,
): AppView => {
    const defaultView = getDefaultAccessibleView(user);
    const normalized = pathname.replace(/^\/+/u, "");
    const resolved = normalized === "" ? defaultView : normalized;
    if (resolved.startsWith("chats/")) {
        return canAccessView("chats", user) ? "chats" : defaultView;
    }
    if (resolved.startsWith("investigations/")) {
        return canAccessView("investigations", user)
            ? "investigations"
            : defaultView;
    }
    if (resolved.startsWith("traces/")) {
        return canAccessView("traces", user) ? "traces" : defaultView;
    }
    if (resolved.startsWith("eval-traces/")) {
        return canAccessView("eval-traces", user) ? "eval-traces" : defaultView;
    }
    if (!isAppView(resolved)) {
        return defaultView;
    }
    if (!canAccessView(resolved, user)) {
        return defaultView;
    }
    return resolved;
};

const AppErrorFallback = ({
    error,
    resetErrorBoundary,
}: FallbackProps): JSX.Element => (
    <PageError
        className="h-screen"
        message={
            error instanceof Error && error.message !== ""
                ? error.message
                : "An unexpected error occurred."
        }
        onRetry={resetErrorBoundary}
    />
);

const AppContent = (): JSX.Element => {
    const { loading: authLoading, user, logout } = useAuth();
    const [sidebarOpen, setSidebarOpen] = useState(
        () => window.localStorage.getItem("internal-sidebar-open") === "true",
    );
    const navigate = useNavigate();
    const { pathname } = useLocation();

    const activeView = useMemo(
        () => resolveView(pathname, user),
        [pathname, user],
    );
    const requestedView = useMemo(() => getRequestedView(pathname), [pathname]);
    const redirectView = useMemo(
        () =>
            user !== undefined &&
            requestedView !== undefined &&
            !canAccessView(requestedView, user)
                ? getDefaultAccessibleView(user)
                : void 0,
        [requestedView, user],
    );

    useEffect(() => {
        const baseTitle = `${UNIVERSITY_NAME} Enrollment Assistant`;
        if (!user) {
            setDocumentTitle(baseTitle);
            return;
        }
        const viewTitle = appViewTitle[activeView];
        setDocumentTitle(`${viewTitle} · ${baseTitle}`);
    }, [activeView, user]);

    useEffect(() => {
        if (!user) {
            return;
        }
        if (redirectView !== undefined) {
            void navigate({
                replace: true,
                search: {
                    chat: undefined,
                    platform: undefined,
                    userId: undefined,
                    userEmail: undefined,
                },
                to: `/${redirectView}`,
            });
        }
    }, [navigate, redirectView, user]);

    const handleLogout = useCallback(async (): Promise<void> => {
        try {
            await logout();
        } catch (error) {
            logger.error("Failed to log out", error);
            const message =
                error instanceof Error && error.message !== ""
                    ? error.message
                    : "Failed to log out. Please try again.";
            toast.error(message);
        }
    }, [logout]);

    const content = authLoading ? (
        <LoadingState className="h-screen" />
    ) : user && redirectView !== undefined ? (
        <LoadingState className="h-screen" />
    ) : user ? (
        <SidebarProvider
            className="h-svh min-h-0 overflow-hidden"
            onOpenChange={(open) => {
                setSidebarOpen(open);
                window.localStorage.setItem(
                    "internal-sidebar-open",
                    String(open),
                );
            }}
            open={sidebarOpen}
        >
            <AppSidebar
                activeView={activeView}
                onLogout={handleLogout}
                onViewChange={(view) => {
                    void navigate({ to: `/${view}` });
                }}
                user={user}
            />
            <SidebarInset className="min-h-0 overflow-hidden">
                <div className="flex min-h-0 flex-1 overflow-hidden">
                    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                        <Outlet />
                    </div>
                </div>
            </SidebarInset>
        </SidebarProvider>
    ) : (
        <AuthPage />
    );

    return (
        <div className="h-screen min-h-screen overflow-hidden font-sans">
            {content}
        </div>
    );
};

export const App = (): JSX.Element => (
    <ThemeProvider>
        <AuthProvider>
            <ErrorBoundary
                FallbackComponent={AppErrorFallback}
                onError={(error, info) => {
                    logger.error("Internal app crashed:", error, info);
                }}
            >
                <AppContent />
            </ErrorBoundary>
            <Toaster />
        </AuthProvider>
    </ThemeProvider>
);
