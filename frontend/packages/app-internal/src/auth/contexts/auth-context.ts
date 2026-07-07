import { createContext, use } from "react";

import type { UserProfile } from "../types";

export type TeamsAuthMode = "outside" | "inside" | "error";

export interface AuthContextValue {
    user?: UserProfile;
    loading: boolean;
    sessionExpired: boolean;
    authError?: string;
    teamsSsoEnabled: boolean;
    teamsSsoLoading: boolean;
    teamsAuthMode: TeamsAuthMode;
    clearAuthError: () => void;
    markSessionExpired: () => void;
    authenticate: () => Promise<void>;
    refreshSession: () => Promise<boolean>;
    signInWithTeamsSso: () => Promise<void>;
    logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(
    undefined,
);

export const useAuth = (): AuthContextValue => {
    const value = use(AuthContext);
    if (value === undefined) {
        throw new Error("useAuth must be used within AuthProvider");
    }
    return value;
};
