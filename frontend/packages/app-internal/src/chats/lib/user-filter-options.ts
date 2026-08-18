import { hasPermission } from "../../auth/lib/permissions";
import type { UserProfile } from "../../auth/types";
import type { ChatUserOption } from "../types";

const USER_OWNER_GROUP_OPTIONS: Record<"staff" | "devs", ChatUserOption> = {
    staff: {
        name: "Staff",
        email: "__owner_group:staff",
        platform: "internal",
        ownerGroup: "staff",
    },
    devs: {
        name: "Devs",
        email: "__owner_group:devs",
        platform: "internal",
        ownerGroup: "devs",
    },
};

export const buildOwnerGroupFilterOptions = (
    user: UserProfile | undefined,
): ChatUserOption[] => {
    const options: ChatUserOption[] = [];

    if (hasPermission(user, "chats_view_users") && hasPermission(user, "chats_view_admins")) {
        options.push(USER_OWNER_GROUP_OPTIONS.staff);
    }

    if (hasPermission(user, "chats_view_devs")) {
        options.push(USER_OWNER_GROUP_OPTIONS.devs);
    }

    return options;
};

export const getUserOptionPrimaryLabel = (
    userOption: ChatUserOption,
): string => userOption.name ?? userOption.email;

export const getUserOptionSecondaryLabel = (
    userOption: ChatUserOption,
): string | undefined =>
    userOption.ownerGroup === undefined &&
    userOption.name !== undefined &&
    userOption.name !== ""
        ? userOption.email
        : undefined;

interface UserFilterQueryParams {
    userEmail?: string;
    userGroup?: "staff" | "devs";
}

export const parseStoredUserFilter = (
    value: unknown,
): ChatUserOption | undefined => {
    if (typeof value !== "object" || value === null) {
        return undefined;
    }

    const email = "email" in value ? value.email : undefined;
    const name = "name" in value ? value.name : undefined;
    const platform = "platform" in value ? value.platform : undefined;
    const ownerGroup = "ownerGroup" in value ? value.ownerGroup : undefined;
    if (
        typeof email !== "string" ||
        email === "" ||
        (platform !== "internal" && platform !== "public") ||
        (ownerGroup !== undefined &&
            ownerGroup !== "staff" &&
            ownerGroup !== "devs")
    ) {
        return undefined;
    }

    return {
        email,
        name: typeof name === "string" ? name : undefined,
        platform,
        ownerGroup,
    };
};

export const buildUserFilterParams = (
    selectedUser: ChatUserOption | undefined,
): UserFilterQueryParams => {
    if (selectedUser?.ownerGroup !== undefined) {
        return { userGroup: selectedUser.ownerGroup };
    }

    const email = selectedUser?.email?.trim();
    return email === undefined || email === "" ? {} : { userEmail: email };
};
