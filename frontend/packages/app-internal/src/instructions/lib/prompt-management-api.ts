import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type {
    ActiveVersion,
    PromptFile,
    PromptSetScope,
    PromptSetVersion,
    PromptSetVersionCreate,
    PromptSetVersionListItem,
} from "../types";

const PROMPT_MANAGEMENT_BASE = "/prompts";

export const fetchDiskTemplates = async (
    api: AuthenticatedApi,
): Promise<PromptFile[]> =>
    api.get<PromptFile[]>(`${PROMPT_MANAGEMENT_BASE}/disk-templates`);

export const fetchVersions = async (
    api: AuthenticatedApi,
    isInternal: boolean,
    scope: PromptSetScope,
): Promise<PromptSetVersionListItem[]> =>
    api.get<PromptSetVersionListItem[]>(
        `${PROMPT_MANAGEMENT_BASE}/versions?is_internal=${String(isInternal)}&scope=${scope}`,
    );

export const fetchDeployedVersion = async (
    api: AuthenticatedApi,
    isInternal: boolean,
    scope: PromptSetScope,
): Promise<ActiveVersion> =>
    api.get<ActiveVersion>(
        `${PROMPT_MANAGEMENT_BASE}/versions/deployed?is_internal=${String(isInternal)}&scope=${scope}`,
    );

export const fetchVersionDetail = async (
    api: AuthenticatedApi,
    versionId: string,
): Promise<PromptSetVersion> =>
    api.get<PromptSetVersion>(
        `${PROMPT_MANAGEMENT_BASE}/versions/${versionId}`,
    );

export const createVersion = async (
    api: AuthenticatedApi,
    data: PromptSetVersionCreate,
): Promise<PromptSetVersion> =>
    api.post<PromptSetVersion>(`${PROMPT_MANAGEMENT_BASE}/versions`, data);

export const deployVersion = async (
    api: AuthenticatedApi,
    versionId: string,
): Promise<PromptSetVersion> =>
    api.post<PromptSetVersion>(
        `${PROMPT_MANAGEMENT_BASE}/versions/${versionId}/deploy`,
        {},
    );

export const undeployVersion = async (
    api: AuthenticatedApi,
    isInternal: boolean,
    scope: PromptSetScope,
): Promise<ActiveVersion> =>
    api.post<ActiveVersion>(
        `${PROMPT_MANAGEMENT_BASE}/versions/undeploy?is_internal=${String(isInternal)}&scope=${scope}`,
        {},
    );

export const deleteVersion = async (
    api: AuthenticatedApi,
    versionId: string,
): Promise<void> => {
    await api.delete(`${PROMPT_MANAGEMENT_BASE}/versions/${versionId}`);
};
