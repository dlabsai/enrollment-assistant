import { apiGet, apiPost } from "@va/shared/lib/api-client";

import type { UserProfile } from "../types";

interface AuthSuccessResponse {
    success: boolean;
}

interface LoginPayload {
    email: string;
    password: string;
}

interface RegisterPayload extends LoginPayload {
    name: string;
    confirm_password: string;
    registration_token: string;
}

interface TeamsSsoPayload {
    token: string;
}

export const loginUser = async (
    payload: LoginPayload,
): Promise<AuthSuccessResponse> =>
    apiPost<AuthSuccessResponse>("/auth/login", payload, {
        credentials: "include",
    });

export const registerUser = async (
    payload: RegisterPayload,
): Promise<AuthSuccessResponse> =>
    apiPost<AuthSuccessResponse>("/auth/register", payload, {
        credentials: "include",
    });

export const fetchCurrentUser = async (): Promise<UserProfile> =>
    apiGet<UserProfile>("/auth/me", {
        credentials: "include",
    });

export const refreshSession = async (): Promise<AuthSuccessResponse> =>
    apiPost<AuthSuccessResponse>(
        "/auth/refresh",
        {},
        { credentials: "include" },
    );

export const loginWithTeamsSso = async (
    payload: TeamsSsoPayload,
): Promise<AuthSuccessResponse> =>
    apiPost<AuthSuccessResponse>("/auth/teams-sso", payload, {
        credentials: "include",
    });

export const logoutUser = async (): Promise<{ success: boolean }> =>
    apiPost<{ success: boolean }>(
        "/auth/logout",
        {},
        {
            credentials: "include",
        },
    );
