export const APP_VIEWS = [
    "chat",
    "chats",
    "messages",
    "feedback",
    "investigate",
    "investigations",
    "usage",
    "traces",
    "analytics",
    "public-analytics",
    "evals",
    "eval-cases",
    "eval-reports",
    "eval-traces",
    "instructions",
    "rag",
    "rag-jobs",
    "rag-viewer",
    "rag-exclusions",
    "rbac",
    "settings",
] as const;

export type AppView = (typeof APP_VIEWS)[number];
const APP_VIEW_SET = new Set<string>(APP_VIEWS);

export const isAppView = (value: string): value is AppView =>
    APP_VIEW_SET.has(value);
