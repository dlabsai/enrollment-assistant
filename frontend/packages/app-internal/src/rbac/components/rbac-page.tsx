import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from "@va/shared/components/ui/sheet";
import { Skeleton } from "@va/shared/components/ui/skeleton";
import { Switch } from "@va/shared/components/ui/switch";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@va/shared/components/ui/table";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "@va/shared/components/ui/tabs";
import { type JSX, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { PageHeader } from "../../components/page-header";
import { PageSection, PageShell } from "../../components/page-shell";
import { InlineError } from "../../components/page-state";
import {
    fetchRbacBootstrap,
    updateGroupPermissions,
    updateUserGroup,
    updateUserOverrides,
} from "../lib/api";
import type {
    RbacBootstrap,
    RbacGroup,
    RbacPermissionDefinition,
    RbacUser,
    RbacUserPermissionOverride,
} from "../types";

const overrideValue = (
    override: RbacUserPermissionOverride | undefined,
): "inherit" | "allow" | "deny" => {
    if (override?.value === true) {
        return "allow";
    }
    if (override?.value === false) {
        return "deny";
    }
    return "inherit";
};

const replaceGroup = (
    bootstrap: RbacBootstrap,
    group: RbacGroup,
): RbacBootstrap => ({
    ...bootstrap,
    groups: bootstrap.groups.map((entry) =>
        entry.id === group.id ? group : entry,
    ),
});

const replaceUser = (
    bootstrap: RbacBootstrap,
    user: RbacUser,
): RbacBootstrap => ({
    ...bootstrap,
    users: bootstrap.users.map((entry) =>
        entry.id === user.id ? user : entry,
    ),
});

const RbacPageSkeleton = (): JSX.Element => (
    <Tabs
        className="flex h-full min-h-0 flex-col gap-4"
        defaultValue="groups"
    >
        <TabsList>
            <TabsTrigger
                disabled
                value="groups"
            >
                Groups
            </TabsTrigger>
            <TabsTrigger
                disabled
                value="users"
            >
                Users
            </TabsTrigger>
        </TabsList>
        <div className="grid h-full min-h-0 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
            <Card className="min-h-0 overflow-auto">
                <CardHeader>
                    <CardTitle>Groups</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                    {Array.from({ length: 3 }, (_unused, index) => (
                        <Skeleton
                            className="h-8 w-full"
                            key={index}
                        />
                    ))}
                </CardContent>
            </Card>
            <Card className="min-h-0 overflow-auto" />
        </div>
    </Tabs>
);

export const RbacPage = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const { authenticate } = useAuth();
    const [bootstrap, setBootstrap] = useState<RbacBootstrap | undefined>();
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | undefined>();
    const [activeGroupId, setActiveGroupId] = useState<string | undefined>();
    const [selectedUserId, setSelectedUserId] = useState<string | undefined>();
    const [userSheetOpen, setUserSheetOpen] = useState(false);
    const [savingGroupId, setSavingGroupId] = useState<string | undefined>();
    const [savingUserId, setSavingUserId] = useState<string | undefined>();

    useEffect(() => {
        let isMounted = true;

        const load = async (): Promise<void> => {
            setLoading(true);
            setError(undefined);
            try {
                const response = await fetchRbacBootstrap(api);
                if (!isMounted) {
                    return;
                }
                setBootstrap(response);
                setActiveGroupId(response.groups[0]?.id);
            } catch (error_) {
                if (!isMounted) {
                    return;
                }
                setError(
                    error_ instanceof Error
                        ? error_.message
                        : "Failed to load access control settings",
                );
            } finally {
                if (isMounted) {
                    setLoading(false);
                }
            }
        };

        void load();

        return (): void => {
            isMounted = false;
        };
    }, [api]);

    const activeGroup = useMemo(
        () => bootstrap?.groups.find((group) => group.id === activeGroupId),
        [activeGroupId, bootstrap?.groups],
    );

    const selectedUser = useMemo(
        () => bootstrap?.users.find((user) => user.id === selectedUserId),
        [bootstrap?.users, selectedUserId],
    );

    const groupedPermissions = useMemo(() => {
        const categories = new Map<string, RbacPermissionDefinition[]>();
        for (const permission of bootstrap?.permissions ?? []) {
            const current = categories.get(permission.category) ?? [];
            current.push(permission);
            categories.set(permission.category, current);
        }
        return [...categories.entries()];
    }, [bootstrap?.permissions]);

    const handleGroupPermissionToggle = async (
        group: RbacGroup,
        permissionKey: string,
        enabled: boolean,
    ): Promise<void> => {
        const enabledKeys = new Set(
            group.permissions
                .filter((permission) => permission.enabled)
                .map((permission) => permission.key),
        );
        if (enabled) {
            enabledKeys.add(permissionKey);
        } else {
            enabledKeys.delete(permissionKey);
        }

        setSavingGroupId(group.id);
        try {
            const updated = await updateGroupPermissions(api, group.id, [
                ...enabledKeys,
            ]);
            setBootstrap((current) =>
                current ? replaceGroup(current, updated) : current,
            );
            await authenticate();
        } catch (error_) {
            toast.error(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to update group permissions",
            );
        } finally {
            setSavingGroupId(undefined);
        }
    };

    const handleUserGroupChange = async (
        userId: string,
        groupId: string,
    ): Promise<void> => {
        setSavingUserId(userId);
        try {
            const updated = await updateUserGroup(api, userId, groupId);
            setBootstrap((current) =>
                current ? replaceUser(current, updated) : current,
            );
            await authenticate();
        } catch (error_) {
            toast.error(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to update user group",
            );
        } finally {
            setSavingUserId(undefined);
        }
    };

    const handleUserOverrideChange = async (
        user: RbacUser,
        permissionKey: string,
        nextValue: "inherit" | "allow" | "deny",
    ): Promise<void> => {
        const overrides = Object.fromEntries(
            user.overrides.map((override) => [
                override.key,
                override.value ?? undefined,
            ]),
        );
        overrides[permissionKey] =
            nextValue === "inherit" ? undefined : nextValue === "allow";

        setSavingUserId(user.id);
        try {
            const updated = await updateUserOverrides(api, user.id, overrides);
            setBootstrap((current) =>
                current ? replaceUser(current, updated) : current,
            );
            await authenticate();
        } catch (error_) {
            toast.error(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to update user overrides",
            );
        } finally {
            setSavingUserId(undefined);
        }
    };

    const pageTabs =
        bootstrap === undefined ? undefined : (
            <Tabs
                className="flex h-full min-h-0 flex-col gap-4"
                defaultValue="groups"
            >
                <TabsList>
                    <TabsTrigger value="groups">Groups</TabsTrigger>
                    <TabsTrigger value="users">Users</TabsTrigger>
                </TabsList>

                <TabsContent
                    className="min-h-0 flex-1"
                    value="groups"
                >
                    <div className="grid h-full min-h-0 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
                        <Card className="min-h-0 overflow-auto">
                            <CardHeader>
                                <CardTitle>Groups</CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-2">
                                {bootstrap.groups.map((group) => (
                                    <Button
                                        className="w-full justify-start"
                                        key={group.id}
                                        onClick={() => {
                                            setActiveGroupId(group.id);
                                        }}
                                        type="button"
                                        variant={
                                            group.id === activeGroupId
                                                ? "default"
                                                : "outline"
                                        }
                                    >
                                        <span className="flex-1 text-left">
                                            {group.name}
                                        </span>
                                    </Button>
                                ))}
                            </CardContent>
                        </Card>

                        <Card className="min-h-0 overflow-auto">
                            <CardHeader>
                                <CardTitle>
                                    {activeGroup?.name ?? "Group permissions"}
                                </CardTitle>
                                <CardDescription>
                                    Toggle the permissions granted by this
                                    group.
                                </CardDescription>
                            </CardHeader>
                            <CardContent className="space-y-6">
                                {activeGroup &&
                                    groupedPermissions.map(
                                        ([category, permissions]) => (
                                            <div
                                                className="space-y-3"
                                                key={category}
                                            >
                                                <div>
                                                    <h3 className="text-sm font-semibold capitalize">
                                                        {category}
                                                    </h3>
                                                </div>
                                                <div className="space-y-3">
                                                    {permissions.map(
                                                        (permission) => {
                                                            const groupPermission =
                                                                activeGroup.permissions.find(
                                                                    (entry) =>
                                                                        entry.key ===
                                                                        permission.key,
                                                                );
                                                            return (
                                                                <div
                                                                    className="flex items-start justify-between gap-4 rounded-lg border p-3"
                                                                    key={
                                                                        permission.key
                                                                    }
                                                                >
                                                                    <div className="space-y-1">
                                                                        <div className="text-sm font-medium">
                                                                            {
                                                                                permission.label
                                                                            }
                                                                        </div>
                                                                        <div className="text-muted-foreground text-xs">
                                                                            {
                                                                                permission.description
                                                                            }
                                                                        </div>
                                                                    </div>
                                                                    <Switch
                                                                        checked={Boolean(
                                                                            groupPermission?.enabled,
                                                                        )}
                                                                        disabled={
                                                                            savingGroupId ===
                                                                            activeGroup.id
                                                                        }
                                                                        onCheckedChange={(
                                                                            checked,
                                                                        ) => {
                                                                            void handleGroupPermissionToggle(
                                                                                activeGroup,
                                                                                permission.key,
                                                                                checked,
                                                                            );
                                                                        }}
                                                                    />
                                                                </div>
                                                            );
                                                        },
                                                    )}
                                                </div>
                                            </div>
                                        ),
                                    )}
                            </CardContent>
                        </Card>
                    </div>
                </TabsContent>

                <TabsContent
                    className="min-h-0 flex-1"
                    value="users"
                >
                    <Card className="h-full min-h-0 overflow-auto">
                        <CardHeader>
                            <CardTitle>Users</CardTitle>
                            <CardDescription>
                                Each user belongs to exactly one group. Per-user
                                overrides win over group permissions.
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>User</TableHead>
                                        <TableHead>Group</TableHead>
                                        <TableHead>Overrides</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {bootstrap.users.map((entry) => {
                                        const selectedGroup =
                                            bootstrap.groups.find(
                                                (group) =>
                                                    group.id === entry.group_id,
                                            );
                                        const overrideCount =
                                            entry.overrides.filter(
                                                (override) =>
                                                    override.value !== null &&
                                                    override.value !==
                                                        undefined,
                                            ).length;
                                        return (
                                            <TableRow key={entry.id}>
                                                <TableCell>
                                                    <div className="min-w-0">
                                                        <div className="truncate text-sm font-medium">
                                                            {entry.name}
                                                        </div>
                                                        <div className="text-muted-foreground truncate text-xs">
                                                            {entry.email}
                                                        </div>
                                                    </div>
                                                </TableCell>
                                                <TableCell>
                                                    <Select
                                                        onValueChange={(
                                                            value,
                                                        ) => {
                                                            if (
                                                                typeof value !==
                                                                "string"
                                                            ) {
                                                                return;
                                                            }
                                                            void handleUserGroupChange(
                                                                entry.id,
                                                                value,
                                                            );
                                                        }}
                                                        value={entry.group_id}
                                                    >
                                                        <SelectTrigger className="w-[180px]">
                                                            <SelectValue placeholder="Select group">
                                                                {
                                                                    selectedGroup?.name
                                                                }
                                                            </SelectValue>
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            {bootstrap.groups.map(
                                                                (group) => (
                                                                    <SelectItem
                                                                        key={
                                                                            group.id
                                                                        }
                                                                        value={
                                                                            group.id
                                                                        }
                                                                    >
                                                                        {
                                                                            group.name
                                                                        }
                                                                    </SelectItem>
                                                                ),
                                                            )}
                                                        </SelectContent>
                                                    </Select>
                                                </TableCell>
                                                <TableCell>
                                                    <Button
                                                        disabled={
                                                            savingUserId ===
                                                            entry.id
                                                        }
                                                        onClick={() => {
                                                            setSelectedUserId(
                                                                entry.id,
                                                            );
                                                            setUserSheetOpen(
                                                                true,
                                                            );
                                                        }}
                                                        type="button"
                                                        variant="outline"
                                                    >
                                                        {overrideCount === 0
                                                            ? "Manage overrides"
                                                            : `${overrideCount} overrides`}
                                                    </Button>
                                                </TableCell>
                                            </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>
        );

    const pageContent = ((): JSX.Element | undefined => {
        if (loading) {
            return <RbacPageSkeleton />;
        }
        if (error !== undefined) {
            return <InlineError message={error} />;
        }
        return pageTabs;
    })();

    return (
        <PageShell variant="dashboard">
            <PageHeader title="Access Controls" />
            <PageSection className="min-h-0 flex-1">{pageContent}</PageSection>

            <Sheet
                onOpenChange={setUserSheetOpen}
                open={userSheetOpen}
            >
                <SheetContent className="flex !w-[min(100vw,960px)] !max-w-[min(100vw,960px)] flex-col gap-4 p-0">
                    <SheetHeader className="border-b px-4 py-4">
                        <SheetTitle>
                            {selectedUser
                                ? `${selectedUser.name} overrides`
                                : "User overrides"}
                        </SheetTitle>
                        <SheetDescription>
                            User-level permissions override group permissions.
                        </SheetDescription>
                    </SheetHeader>
                    <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
                        {selectedUser ? (
                            <div className="space-y-6">
                                {groupedPermissions.map(
                                    ([category, permissions]) => (
                                        <div
                                            className="space-y-3"
                                            key={category}
                                        >
                                            <h3 className="text-sm font-semibold capitalize">
                                                {category}
                                            </h3>
                                            <div className="space-y-3">
                                                {permissions.map(
                                                    (permission) => {
                                                        const override =
                                                            selectedUser.overrides.find(
                                                                (entry) =>
                                                                    entry.key ===
                                                                    permission.key,
                                                            );
                                                        const effectiveValue =
                                                            selectedUser
                                                                .effective_permissions[
                                                                permission.key
                                                            ];
                                                        return (
                                                            <div
                                                                className="grid gap-3 rounded-lg border p-3 lg:grid-cols-[minmax(0,1fr)_220px]"
                                                                key={
                                                                    permission.key
                                                                }
                                                            >
                                                                <div className="space-y-1">
                                                                    <div className="text-sm font-medium">
                                                                        {
                                                                            permission.label
                                                                        }
                                                                    </div>
                                                                    <div className="text-muted-foreground text-xs">
                                                                        {
                                                                            permission.description
                                                                        }
                                                                    </div>
                                                                    <div className="text-muted-foreground text-xs">
                                                                        Effective:{" "}
                                                                        {effectiveValue
                                                                            ? "allowed"
                                                                            : "denied"}
                                                                    </div>
                                                                </div>
                                                                <Select
                                                                    onValueChange={(
                                                                        value,
                                                                    ) => {
                                                                        if (
                                                                            value !==
                                                                                "inherit" &&
                                                                            value !==
                                                                                "allow" &&
                                                                            value !==
                                                                                "deny"
                                                                        ) {
                                                                            return;
                                                                        }
                                                                        void handleUserOverrideChange(
                                                                            selectedUser,
                                                                            permission.key,
                                                                            value,
                                                                        );
                                                                    }}
                                                                    value={overrideValue(
                                                                        override,
                                                                    )}
                                                                >
                                                                    <SelectTrigger>
                                                                        <SelectValue placeholder="Inherit" />
                                                                    </SelectTrigger>
                                                                    <SelectContent>
                                                                        <SelectItem value="inherit">
                                                                            Inherit
                                                                        </SelectItem>
                                                                        <SelectItem value="allow">
                                                                            Allow
                                                                        </SelectItem>
                                                                        <SelectItem value="deny">
                                                                            Deny
                                                                        </SelectItem>
                                                                    </SelectContent>
                                                                </Select>
                                                            </div>
                                                        );
                                                    },
                                                )}
                                            </div>
                                        </div>
                                    ),
                                )}
                            </div>
                        ) : undefined}
                    </div>
                </SheetContent>
            </Sheet>
        </PageShell>
    );
};
