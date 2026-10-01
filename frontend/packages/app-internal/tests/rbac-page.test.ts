// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, test, vi } from "vitest";

import { RbacPage } from "../src/rbac/components/rbac-page";
import type { RbacBootstrap } from "../src/rbac/types";

const api = vi.hoisted(() => ({
    get: vi.fn<(endpoint: string) => Promise<unknown>>(),
    put: vi.fn<(endpoint: string, body: unknown) => Promise<unknown>>(),
}));
const authenticate = vi.hoisted(() => vi.fn<() => Promise<void>>());
const toastSuccess = vi.hoisted(() => vi.fn<(message: string) => void>());

vi.mock("sonner", () => ({
    toast: {
        error: vi.fn(),
        success: toastSuccess,
    },
}));
vi.mock("../src/auth/hooks/use-authenticated-api", () => ({
    useAuthenticatedApi: () => api,
}));
vi.mock("../src/auth/contexts/auth-context", () => ({
    useAuth: () => ({ authenticate }),
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const bootstrap: RbacBootstrap = {
    permissions: [
        {
            key: "access_rbac",
            label: "Access controls",
            description: "Manage access controls.",
            category: "pages",
        },
    ],
    groups: [
        {
            id: "11111111-1111-4111-8111-111111111111",
            slug: "user",
            name: "Users",
            is_system: true,
            permissions: [{ key: "access_rbac", enabled: false }],
        },
        {
            id: "22222222-2222-4222-8222-222222222222",
            slug: "admin",
            name: "Administrators",
            is_system: true,
            permissions: [{ key: "access_rbac", enabled: true }],
        },
    ],
    users: [
        {
            id: "33333333-3333-4333-8333-333333333333",
            email: "alice@example.com",
            name: "Alice User",
            created_at: "2026-02-01T12:00:00Z",
            group_id: "11111111-1111-4111-8111-111111111111",
            group_slug: "user",
            overrides: [{ key: "access_rbac", value: null }],
            effective_permissions: { access_rbac: false },
        },
        {
            id: "44444444-4444-4444-8444-444444444444",
            email: "bob@example.com",
            name: "Bob Admin",
            created_at: "2026-01-01T12:00:00Z",
            group_id: "22222222-2222-4222-8222-222222222222",
            group_slug: "admin",
            overrides: [{ key: "access_rbac", value: true }],
            effective_permissions: { access_rbac: true },
        },
    ],
};

const settle = async (): Promise<void> =>
    new Promise((resolve) => setTimeout(resolve, 0));

const findButton = (label: string): HTMLButtonElement => {
    const found = [...document.querySelectorAll("button")].find(
        (candidate) =>
            candidate.getAttribute("aria-label") === label ||
            candidate.textContent?.trim() === label,
    );
    assert.ok(found, `Missing button: ${label}`);
    return found;
};

const clickButton = async (label: string): Promise<void> => {
    await act(async () => {
        findButton(label).click();
        await settle();
    });
};

const setInputValue = async (
    input: HTMLInputElement,
    value: string,
): Promise<void> => {
    await act(async () => {
        Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype,
            "value",
        )?.set?.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        await settle();
    });
};

const tableRows = (host: HTMLElement): HTMLTableRowElement[] =>
    [...host.querySelectorAll<HTMLTableRowElement>("tbody tr")];

const tableUserNames = (host: HTMLElement): (string | undefined)[] =>
    tableRows(host).map((row) => row.querySelector("td")?.textContent?.trim());

beforeEach(() => {
    api.get.mockReset();
    api.put.mockReset();
    authenticate.mockReset();
    toastSuccess.mockReset();
    api.get.mockResolvedValue(bootstrap);
    authenticate.mockResolvedValue();
});

test("changing a user group shows a success toast", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const updatedUser = {
        ...bootstrap.users[0],
        group_id: bootstrap.groups[1].id,
        group_slug: bootstrap.groups[1].slug,
    };
    api.put.mockResolvedValue(updatedUser);

    await act(async () => {
        root.render(createElement(RbacPage));
        await settle();
    });
    await act(settle);

    try {
        await clickButton("Group for Alice User");
        const administrators = [
            ...document.querySelectorAll<HTMLElement>(
                '[data-slot="select-item"]',
            ),
        ].find((item) => item.textContent?.trim() === "Administrators");
        assert.ok(administrators);

        await act(async () => {
            administrators.focus();
            await settle();
            administrators.click();
            await settle();
        });

        assert.deepEqual(toastSuccess.mock.calls, [["User group updated"]]);
    } finally {
        await act(async () => root.unmount());
        host.remove();
    }
});

test("users can search and sort the user table and open row overrides", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);

    await act(async () => {
        root.render(createElement(RbacPage));
        await settle();
    });
    await act(settle);

    try {
        const tabLabels = [
            ...host.querySelectorAll<HTMLElement>('[data-slot="tabs-trigger"]'),
        ].map((tab) => tab.textContent?.trim());
        assert.deepEqual(tabLabels, ["Users", "Groups"]);
        assert.equal(findButton("Users").hasAttribute("data-active"), true);

        const headers = [...host.querySelectorAll("th")].map((header) =>
            header.textContent?.trim(),
        );
        assert.ok(headers.includes("Created"));
        assert.deepEqual(tableUserNames(host), ["Alice User", "Bob Admin"]);

        const search = host.querySelector<HTMLInputElement>(
            'input[aria-label="Search users"]',
        );
        assert.ok(search);
        await setInputValue(search, "administrators");
        assert.deepEqual(tableUserNames(host), ["Bob Admin"]);

        await setInputValue(search, "");
        await clickButton("Created");
        await clickButton("Created");
        assert.deepEqual(tableUserNames(host), ["Bob Admin", "Alice User"]);

        await clickButton("Open actions for Bob Admin");
        const manageOverrides = [
            ...document.querySelectorAll<HTMLElement>(
                '[data-slot="dropdown-menu-item"]',
            ),
        ].find((item) => item.textContent?.trim() === "Manage overrides");
        assert.ok(manageOverrides);
        await act(async () => {
            manageOverrides.click();
            await settle();
        });
        assert.match(document.body.textContent ?? "", /Bob Admin overrides/u);
    } finally {
        await act(async () => root.unmount());
        host.remove();
    }
});
