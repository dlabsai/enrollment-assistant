import type { PermissionKey,UserProfile } from "../types";

export const hasPermission = (
    user: UserProfile | undefined,
    permissionKey: PermissionKey,
): boolean => user?.permissions[permissionKey] === true;
