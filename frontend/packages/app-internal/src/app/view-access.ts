import { hasPermission } from "../auth/lib/permissions";
import type { UserProfile } from "../auth/types";
import { APP_VIEWS, type AppView } from "./feature-flags";

export const canAccessView = (
    view: AppView,
    user: UserProfile | undefined,
): boolean => {
    switch (view) {
        case "chat": {
            return true;
        }
        case "chats": {
            return hasPermission(user, "access_chats");
        }
        case "messages": {
            return hasPermission(user, "access_messages");
        }
        case "feedback": {
            return hasPermission(user, "access_chats");
        }
        case "investigate":
        case "investigations": {
            return hasPermission(user, "access_investigations");
        }
        case "instructions": {
            return hasPermission(user, "access_instructions");
        }
        case "traces": {
            return hasPermission(user, "access_traces");
        }
        case "rag":
        case "rag-jobs": {
            return hasPermission(user, "access_rag");
        }
        case "rag-viewer": {
            return hasPermission(user, "access_rag_viewer");
        }
        case "rag-exclusions": {
            return hasPermission(user, "access_rag_exclusions");
        }
        case "rbac": {
            return hasPermission(user, "access_rbac");
        }
        case "usage": {
            return hasPermission(user, "access_usage");
        }
        case "analytics": {
            return hasPermission(user, "access_analytics");
        }
        case "public-analytics": {
            return hasPermission(user, "access_public_analytics");
        }
        case "evals":
        case "eval-cases":
        case "eval-reports":
        case "eval-traces": {
            return hasPermission(user, "access_evals");
        }
        case "settings": {
            return hasPermission(user, "access_settings");
        }
        default: {
            const exhaustiveCheck: never = view;
            return exhaustiveCheck;
        }
    }
};

export const getDefaultAccessibleView = (
    user: UserProfile | undefined,
): AppView => APP_VIEWS.find((view) => canAccessView(view, user)) ?? "chat";
