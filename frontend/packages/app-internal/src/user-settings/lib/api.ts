import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type { UserSettings } from "../types";

export const fetchUserSettings = async (
    api: AuthenticatedApi,
    signal: AbortSignal,
): Promise<UserSettings> => api.get<UserSettings>("/user-settings", { signal });

export const saveUserSettings = async (
    api: AuthenticatedApi,
    personalInstructions: string,
): Promise<UserSettings> =>
    api.put<UserSettings>("/user-settings", {
        personal_instructions: personalInstructions,
    });
