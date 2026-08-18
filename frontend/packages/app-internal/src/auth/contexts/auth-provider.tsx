import { isApiError } from "@va/shared/lib/api-client";
import { logger } from "@va/shared/lib/logger";
import {
    type JSX,
    type ReactNode,
    useCallback,
    useEffect,
    useMemo,
    useState,
} from "react";

import {
    fetchCurrentUser,
    loginWithTeamsSso,
    logoutUser,
    refreshSession as refreshSessionApi,
} from "../lib/api";
import {
    isRunningInTeams,
    isTeamsForceModeEnabled,
    isTeamsLikelyByProxy,
    isTeamsSsoEnabled,
    requestTeamsSsoToken,
} from "../lib/teams-sso";
import type { UserProfile } from "../types";
import {
    AuthContext,
    type AuthContextValue,
    type TeamsAuthMode,
} from "./auth-context";

const fetchAndStoreUser = async (
    setUser: (user?: UserProfile) => void,
): Promise<void> => {
    const profile = await fetchCurrentUser();
    setUser(profile);
};

interface AuthProviderProps {
    children: ReactNode;
}

const getErrorMessage = (error: unknown, fallback: string): string =>
    error instanceof Error && error.message !== "" ? error.message : fallback;

const isUnauthorizedError = (error: unknown): boolean =>
    isApiError(error) && error.status === 401;

const TEMPORARY_AUTH_ERROR =
    "Authentication is temporarily unavailable. Please try again.";

export const AuthProvider = ({ children }: AuthProviderProps): JSX.Element => {
    const [user, setUser] = useState<UserProfile | undefined>();
    const [loading, setLoading] = useState(true);
    const [sessionExpired, setSessionExpired] = useState(false);
    const [authError, setAuthError] = useState<string | undefined>();
    const [teamsSsoLoading, setTeamsSsoLoading] = useState(false);
    const [teamsAuthMode, setTeamsAuthMode] =
        useState<TeamsAuthMode>("outside");
    const teamsSsoEnabled = isTeamsSsoEnabled();
    const teamsForceModeEnabled = isTeamsForceModeEnabled();

    const clearAuthState = useCallback(
        (options: { sessionExpired: boolean }) => {
            setUser(undefined);
            setSessionExpired(options.sessionExpired);
        },
        [],
    );

    const clearAuthError = useCallback(() => {
        setAuthError(undefined);
    }, []);

    const completeAuthentication = useCallback(async () => {
        await fetchAndStoreUser(setUser);
        setSessionExpired(false);
        setAuthError(undefined);
    }, []);

    const runTeamsSsoLogin = useCallback(async () => {
        setAuthError(undefined);
        setTeamsSsoLoading(true);

        try {
            const teamsToken = await requestTeamsSsoToken();
            await loginWithTeamsSso({ token: teamsToken });
            await completeAuthentication();
        } finally {
            setTeamsSsoLoading(false);
        }
    }, [completeAuthentication]);

    const refreshSessionToken = useCallback(async (): Promise<boolean> => {
        try {
            await refreshSessionApi();
            await completeAuthentication();
            return true;
        } catch (error) {
            logger.warn("Failed to refresh session", error);
            if (!isUnauthorizedError(error)) {
                throw error;
            }
            clearAuthState({ sessionExpired: false });
            return false;
        }
    }, [clearAuthState, completeAuthentication]);

    useEffect(() => {
        const initialize = async (): Promise<void> => {
            try {
                await completeAuthentication();
            } catch (error) {
                logger.warn("Failed to restore session", error);
                if (!isUnauthorizedError(error)) {
                    setAuthError(TEMPORARY_AUTH_ERROR);
                    return;
                }

                try {
                    if (await refreshSessionToken()) {
                        return;
                    }
                } catch {
                    setAuthError(TEMPORARY_AUTH_ERROR);
                    return;
                }

                if (!teamsForceModeEnabled) {
                    const nextTeamsAuthMode = isTeamsLikelyByProxy()
                        ? "inside"
                        : "outside";
                    setTeamsAuthMode(nextTeamsAuthMode);
                    if (nextTeamsAuthMode !== "inside") {
                        return;
                    }
                }

                try {
                    await runTeamsSsoLogin();
                } catch (teamsError) {
                    logger.warn(
                        "Automatic Microsoft Teams sign-in failed",
                        teamsError,
                    );
                    setAuthError(
                        getErrorMessage(
                            teamsError,
                            "Microsoft Teams authentication failed.",
                        ),
                    );
                }
            } finally {
                setLoading(false);
            }
        };

        void initialize();
    }, [
        completeAuthentication,
        refreshSessionToken,
        runTeamsSsoLogin,
        teamsForceModeEnabled,
    ]);

    useEffect(() => {
        let active = true;
        if (teamsSsoEnabled && user !== undefined) {
            void isRunningInTeams().then(
                (runningInTeams) => {
                    if (active) {
                        setTeamsAuthMode(runningInTeams ? "inside" : "outside");
                    }
                },
                (error: unknown) => {
                    if (active) {
                        logger.warn(
                            "Failed to detect Microsoft Teams environment",
                            error,
                        );
                        setTeamsAuthMode("error");
                        setAuthError(
                            getErrorMessage(
                                error,
                                "Failed to initialize Microsoft Teams authentication.",
                            ),
                        );
                    }
                },
            );
        }

        return (): void => {
            active = false;
        };
    }, [teamsSsoEnabled, user]);

    const markSessionExpired = useCallback(() => {
        clearAuthState({ sessionExpired: true });
    }, [clearAuthState]);

    const authenticate = useCallback(async () => {
        await completeAuthentication();
    }, [completeAuthentication]);

    const signInWithTeamsSso = useCallback(async () => {
        if (!teamsSsoEnabled) {
            throw new Error(
                "Microsoft Teams SSO is not enabled for this build",
            );
        }

        await runTeamsSsoLogin();
    }, [runTeamsSsoLogin, teamsSsoEnabled]);

    const logout = useCallback(async () => {
        await logoutUser();
        clearAuthState({ sessionExpired: false });
    }, [clearAuthState]);

    const value = useMemo<AuthContextValue>(
        () => ({
            user,
            loading,
            sessionExpired,
            authError,
            teamsSsoEnabled,
            teamsSsoLoading,
            teamsAuthMode,
            clearAuthError,
            markSessionExpired,
            authenticate,
            refreshSession: refreshSessionToken,
            signInWithTeamsSso,
            logout,
        }),
        [
            user,
            loading,
            sessionExpired,
            authError,
            teamsSsoEnabled,
            teamsSsoLoading,
            teamsAuthMode,
            clearAuthError,
            markSessionExpired,
            authenticate,
            refreshSessionToken,
            signInWithTeamsSso,
            logout,
        ],
    );

    return <AuthContext value={value}>{children}</AuthContext>;
};
