import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type { RbacBootstrap, RbacGroup, RbacUser } from "../types";

export const fetchRbacBootstrap = async (
    api: AuthenticatedApi,
): Promise<RbacBootstrap> => api.get<RbacBootstrap>("/rbac/bootstrap");

export const updateGroupPermissions = async (
    api: AuthenticatedApi,
    groupId: string,
    permissionKeys: string[],
): Promise<RbacGroup> =>
    api.put<RbacGroup>(`/rbac/groups/${groupId}/permissions`, {
        permission_keys: permissionKeys,
    });

export const updateUserGroup = async (
    api: AuthenticatedApi,
    userId: string,
    groupId: string,
): Promise<RbacUser> =>
    api.put<RbacUser>(`/rbac/users/${userId}/group`, {
        group_id: groupId,
    });

export const updateUserOverrides = async (
    api: AuthenticatedApi,
    userId: string,
    overrides: Record<string, boolean | undefined>,
): Promise<RbacUser> =>
    api.put<RbacUser>(`/rbac/users/${userId}/permission-overrides`, {
        overrides,
    });
