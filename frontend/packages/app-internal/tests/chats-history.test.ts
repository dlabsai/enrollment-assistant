// @vitest-environment happy-dom
import assert from "node:assert/strict";

import {
    createMemoryHistory,
    createRootRoute,
    createRoute,
    createRouter,
    RouterProvider,
} from "@tanstack/react-router";
import { act, createElement, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { test, vi } from "vitest";

import { ChatsPage } from "../src/chats/components/chats-page";
import { validateChatsSearch } from "../src/chats/lib/search-state";
import type { TimeRangeFilter } from "../src/components/time-range-filter";
import type { UserFilterPopover } from "../src/components/user-filter-popover";

const requests = vi.hoisted(() => [] as string[]);
vi.mock("../src/auth/hooks/use-authenticated-api", () => {
    const api = {
        get: async (endpoint: string) => {
            requests.push(endpoint);
            return { items: [], total: 100 };
        },
    };
    return { useAuthenticatedApi: () => api };
});
vi.mock("../src/auth/contexts/auth-context", () => ({
    useAuth: () => ({
        user: {
            email: "reviewer@example.com",
            group: { slug: "dev" },
            permissions: {
                access_chats: true,
                chats_view_users: true,
                chats_view_admins: true,
            },
        },
    }),
}));
vi.mock("../src/components/user-filter-popover", () => ({
    UserFilterPopover: ({ label }: ComponentProps<typeof UserFilterPopover>) =>
        createElement("output", { "data-testid": "owner" }, label),
}));
vi.mock("../src/components/time-range-filter", () => ({
    TimeRangeFilter: ({
        value,
        customRange,
    }: ComponentProps<typeof TimeRangeFilter>) =>
        createElement(
            "output",
            { "data-testid": "range" },
            JSON.stringify({ value, ...customRange }),
        ),
}));
vi.mock("../src/components/data-table", () => ({ DataTable: () => null }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

test("Clear, Back and Forward restore the Chats request and visible filters", async () => {
    localStorage.clear();
    const url =
        "/chats?analyticsStart=2026-08-10T00:00:00Z&analyticsEndBefore=2026-08-11T00:00:00Z&platform=internal&userGroup=staff";
    const history = createMemoryHistory({ initialEntries: [url] });
    const rootRoute = createRootRoute();
    const route = createRoute({
        getParentRoute: () => rootRoute,
        path: "/chats",
        validateSearch: validateChatsSearch,
        component: ChatsPage,
    });
    const router = createRouter({
        routeTree: rootRoute.addChildren([route]),
        history,
    });
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const settle = async (): Promise<void> => {
        await new Promise((resolve) => setTimeout(resolve, 0));
    };
    const click = async (label: string): Promise<void> => {
        const button = [...container.querySelectorAll("button")].find(
            (node) => node.textContent?.trim() === label,
        );
        assert.ok(button, label);
        await act(async () => {
            button.click();
            await settle();
        });
    };
    const latest = (): URL => {
        assert.ok(requests.length);
        return new URL(requests[requests.length - 1], "http://testserver");
    };
    try {
        await act(async () => {
            await router.load();
            root.render(createElement(RouterProvider, { router }));
            await settle();
        });
        await act(settle);
        assert.equal(latest().searchParams.get("user_group"), "staff");
        await click("Clear");
        assert.equal(latest().searchParams.has("analytics_start"), false);
        assert.equal(latest().searchParams.has("user_group"), false);
        assert.equal(
            container.querySelector('[data-testid="owner"]')?.textContent,
            "All users",
        );
        assert.match(
            container.querySelector('[data-testid="range"]')?.textContent ?? "",
            /30d/,
        );
        const beforeBack = requests.length;
        await act(async () => {
            history.back();
            await settle();
        });
        await act(settle);
        assert.ok(requests.length > beforeBack);
        for (const request of requests.slice(beforeBack)) {
            const params = new URL(request, "http://testserver").searchParams;
            assert.equal(params.get("user_group"), "staff");
            assert.equal(params.get("analytics_start"), "2026-08-10T00:00:00Z");
            assert.equal(
                params.get("analytics_end_before"),
                "2026-08-11T00:00:00Z",
            );
            assert.equal(params.get("platform"), "internal");
        }
        assert.equal(
            container.querySelector('[data-testid="owner"]')?.textContent,
            "Staff",
        );
        assert.deepEqual(
            JSON.parse(
                container.querySelector('[data-testid="range"]')?.textContent ??
                    "{}",
            ),
            {
                value: "custom",
                start: "2026-08-10T00:00:00.000Z",
                end: "2026-08-11T00:00:00.000Z",
            },
        );
        await act(async () => {
            history.forward();
            await settle();
        });
        await act(settle);
        assert.equal(latest().searchParams.has("analytics_start"), false);
        assert.equal(latest().searchParams.has("user_group"), false);
        assert.match(
            container.querySelector('[data-testid="range"]')?.textContent ?? "",
            /30d/,
        );
    } finally {
        await act(() => root.unmount());
        container.remove();
        history.destroy();
        localStorage.clear();
    }
});
