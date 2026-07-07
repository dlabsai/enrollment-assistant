import {
    type ApiBlobResponse,
    type ApiClientOptions,
    apiDelete,
    apiGet,
    apiGetBlob,
    apiPost,
    apiPostStream,
    apiPut,
    isApiError,
} from "@va/shared/lib/api-client";
import { useMemo } from "react";

import { useAuth } from "../contexts/auth-context";

const withSessionExpiry = async <T>(
    operation: () => Promise<T>,
    refreshSession: () => Promise<boolean>,
    onExpire: () => void,
): Promise<T> => {
    try {
        return await operation();
    } catch (error) {
        if (isApiError(error) && error.status === 401) {
            const refreshedSession = await refreshSession();
            if (refreshedSession) {
                return operation();
            }
            onExpire();
        }
        throw error;
    }
};

export const useAuthenticatedApi = (): {
    get: <T>(endpoint: string, options?: ApiClientOptions) => Promise<T>;
    getBlob: (
        endpoint: string,
        options?: ApiClientOptions,
    ) => Promise<ApiBlobResponse>;
    post: <T>(
        endpoint: string,
        body: unknown,
        options?: ApiClientOptions,
    ) => Promise<T>;
    postStream: (
        endpoint: string,
        body: unknown,
        options?: ApiClientOptions,
    ) => Promise<Response>;
    put: <T>(
        endpoint: string,
        body: unknown,
        options?: ApiClientOptions,
    ) => Promise<T>;
    delete: (endpoint: string, options?: ApiClientOptions) => Promise<void>;
} => {
    const { markSessionExpired, refreshSession } = useAuth();

    return useMemo(
        () => ({
            get: async <T>(endpoint: string, options?: ApiClientOptions) =>
                withSessionExpiry(
                    async () =>
                        apiGet<T>(endpoint, {
                            ...options,
                            credentials: options?.credentials ?? "include",
                        }),
                    refreshSession,
                    markSessionExpired,
                ),

            getBlob: async (endpoint: string, options?: ApiClientOptions) =>
                withSessionExpiry(
                    async () =>
                        apiGetBlob(endpoint, {
                            ...options,
                            credentials: options?.credentials ?? "include",
                        }),
                    refreshSession,
                    markSessionExpired,
                ),

            post: async <T>(
                endpoint: string,
                body: unknown,
                options?: ApiClientOptions,
            ) =>
                withSessionExpiry(
                    async () =>
                        apiPost<T>(endpoint, body, {
                            ...options,
                            credentials: options?.credentials ?? "include",
                        }),
                    refreshSession,
                    markSessionExpired,
                ),

            postStream: async (
                endpoint: string,
                body: unknown,
                options?: ApiClientOptions,
            ) =>
                withSessionExpiry(
                    async () =>
                        apiPostStream(endpoint, body, {
                            ...options,
                            credentials: options?.credentials ?? "include",
                        }),
                    refreshSession,
                    markSessionExpired,
                ),

            put: async <T>(
                endpoint: string,
                body: unknown,
                options?: ApiClientOptions,
            ) =>
                withSessionExpiry(
                    async () =>
                        apiPut<T>(endpoint, body, {
                            ...options,
                            credentials: options?.credentials ?? "include",
                        }),
                    refreshSession,
                    markSessionExpired,
                ),

            delete: async (endpoint: string, options?: ApiClientOptions) =>
                withSessionExpiry(
                    async () =>
                        apiDelete(endpoint, {
                            ...options,
                            credentials: options?.credentials ?? "include",
                        }),
                    refreshSession,
                    markSessionExpired,
                ),
        }),
        [refreshSession, markSessionExpired],
    );
};

export type AuthenticatedApi = ReturnType<typeof useAuthenticatedApi>;
