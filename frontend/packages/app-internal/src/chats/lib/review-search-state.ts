import type { ChatUserOption } from "../types";

export const parseRouteDate = (value: string | undefined): Date | undefined => {
    if (value === undefined || value === "") {
        return undefined;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
};

export const parseRouteDateRange = (
    start: unknown,
    end: unknown,
    endBefore?: unknown,
): { start?: string; end?: string; endBefore?: string } | undefined => {
    if (end !== undefined && endBefore !== undefined) {
        return undefined;
    }
    for (const value of [start, end, endBefore]) {
        if (
            value !== undefined &&
            (typeof value !== "string" || parseRouteDate(value) === undefined)
        ) {
            return undefined;
        }
    }
    const range = {
        start: typeof start === "string" ? start : undefined,
        end: typeof end === "string" ? end : undefined,
        ...(typeof endBefore === "string" ? { endBefore } : {}),
    };
    if (
        range.start !== undefined &&
        range.end !== undefined &&
        new Date(range.start) > new Date(range.end)
    ) {
        return undefined;
    }
    if (
        range.start !== undefined &&
        range.endBefore !== undefined &&
        range.start === range.endBefore
    ) {
        return undefined;
    }
    if (
        range.start !== undefined &&
        range.endBefore !== undefined &&
        new Date(range.start) > new Date(range.endBefore)
    ) {
        return undefined;
    }
    return range;
};

export const routeUserOption = (
    userEmail: string | undefined,
    userGroup: "staff" | "devs" | undefined,
    platform: "internal" | "public" | undefined,
): ChatUserOption | undefined => {
    if (userGroup !== undefined) {
        return {
            name: userGroup === "staff" ? "Staff" : "Devs",
            email: `__owner_group:${userGroup}`,
            platform: "internal",
            ownerGroup: userGroup,
        };
    }
    if (userEmail === undefined || userEmail === "") {
        return undefined;
    }
    return { email: userEmail, platform: platform ?? "internal" };
};
