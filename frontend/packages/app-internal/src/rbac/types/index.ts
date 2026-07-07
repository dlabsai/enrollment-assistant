export interface RbacPermissionDefinition {
    key: string;
    label: string;
    description: string;
    category: string;
}

export interface RbacGroupPermission {
    key: string;
    enabled: boolean;
}

export interface RbacGroup {
    id: string;
    slug: string;
    name: string;
    description?: string;
    is_system: boolean;
    permissions: RbacGroupPermission[];
}

export interface RbacUserPermissionOverride {
    key: string;
    value?: boolean | null;
}

export interface RbacUser {
    id: string;
    email: string;
    name: string;
    group_id: string;
    group_slug: string;
    overrides: RbacUserPermissionOverride[];
    effective_permissions: Record<string, boolean>;
}

export interface RbacBootstrap {
    permissions: RbacPermissionDefinition[];
    groups: RbacGroup[];
    users: RbacUser[];
}
