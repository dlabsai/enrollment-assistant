import type * as TeamsJs from "@microsoft/teams-js";
import { logger } from "@va/shared/lib/logger";

const TEAMS_SSO_ENABLED =
    String(import.meta.env.VITE_TEAMS_SSO_ENABLED ?? "false") === "true";
const TEAMS_FORCE_MODE =
    String(import.meta.env.VITE_TEAMS_FORCE_MODE ?? "false") === "true";
const TEAMS_INITIALIZE_TIMEOUT_MS = 1500;
const TEAMS_TOKEN_TIMEOUT_MS = 10_000;

type TeamsSdk = typeof TeamsJs;

const teamsInitializationState: { promise?: Promise<TeamsSdk> } = {};

const TEAMS_PARENT_WINDOW_MISSING_MESSAGE =
    "Initialization Failed. No Parent window found.";

const isTopLevelWindow = (): boolean => {
    try {
        return window.self === window.top;
    } catch {
        return false;
    }
};

const isTeamsParentWindowMissingError = (error: unknown): boolean =>
    error instanceof Error &&
    error.message.includes(TEAMS_PARENT_WINDOW_MISSING_MESSAGE);

const isTeamsUnavailableError = (error: unknown): boolean =>
    error instanceof Error &&
    error.message ===
        "Microsoft Teams SSO is not available in this environment";

const withTimeout = async <T>(
    operation: Promise<T>,
    timeoutMs: number,
    message: string,
): Promise<T> => {
    const timeoutState: {
        handle?: ReturnType<typeof window.setTimeout>;
    } = {};

    const timeoutPromise = new Promise<never>((unusedResolve, reject) => {
        void unusedResolve;
        timeoutState.handle = window.setTimeout(() => {
            reject(new Error(message));
        }, timeoutMs);
    });

    try {
        return await Promise.race([operation, timeoutPromise]);
    } finally {
        if (timeoutState.handle !== undefined) {
            window.clearTimeout(timeoutState.handle);
        }
    }
};

const initializeTeamsSdk = async (): Promise<TeamsSdk> => {
    if (!TEAMS_SSO_ENABLED) {
        throw new Error("Microsoft Teams SSO is not enabled for this build");
    }

    const teams = await import("@microsoft/teams-js");

    try {
        await withTimeout(
            teams.app.initialize(),
            TEAMS_INITIALIZE_TIMEOUT_MS,
            "Timed out while initializing Microsoft Teams",
        );
        await withTimeout(
            teams.app.getContext(),
            TEAMS_INITIALIZE_TIMEOUT_MS,
            "Timed out while reading Microsoft Teams context",
        );
        return teams;
    } catch (error) {
        if (isTopLevelWindow() && isTeamsParentWindowMissingError(error)) {
            logger.debug("Microsoft Teams SDK is unavailable", error);
            throw new Error(
                "Microsoft Teams SSO is not available in this environment",
                { cause: error },
            );
        }

        logger.warn("Failed to initialize Microsoft Teams SDK", error);
        throw new Error("Failed to initialize Microsoft Teams SDK", {
            cause: error,
        });
    }
};

const getInitializedTeamsSdk = async (): Promise<TeamsSdk> => {
    teamsInitializationState.promise ??= initializeTeamsSdk();

    try {
        return await teamsInitializationState.promise;
    } catch (error) {
        delete teamsInitializationState.promise;
        throw error;
    }
};

export const isTeamsSsoEnabled = (): boolean => TEAMS_SSO_ENABLED;

export const isTeamsForceModeEnabled = (): boolean =>
    TEAMS_SSO_ENABLED && TEAMS_FORCE_MODE;

export const isTeamsLikelyByProxy = (): boolean =>
    TEAMS_SSO_ENABLED && !isTopLevelWindow();

export const isRunningInTeams = async (): Promise<boolean> => {
    if (!TEAMS_SSO_ENABLED || isTopLevelWindow()) {
        return false;
    }

    try {
        await getInitializedTeamsSdk();
        return true;
    } catch (error) {
        if (isTeamsUnavailableError(error)) {
            return false;
        }
        throw error;
    }
};

export const requestTeamsSsoToken = async (): Promise<string> => {
    const teams = await getInitializedTeamsSdk();

    try {
        return await withTimeout(
            teams.authentication.getAuthToken(),
            TEAMS_TOKEN_TIMEOUT_MS,
            "Timed out while requesting a Microsoft Teams SSO token",
        );
    } catch (error) {
        logger.warn("Failed to obtain Microsoft Teams SSO token", error);
        throw new Error("Failed to obtain a Microsoft Teams SSO token", {
            cause: error,
        });
    }
};
