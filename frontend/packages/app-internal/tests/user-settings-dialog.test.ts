// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { SidebarProvider } from "@va/shared/components/ui/sidebar";
import { act, createElement, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, test, vi } from "vitest";

import { AppSidebar } from "../src/app/components/app-sidebar";
import type { PermissionKey, UserProfile } from "../src/auth/types";
import { formatLocaleNumber } from "../src/lib/number-format";
import { UserSettingsDialog } from "../src/user-settings/components/user-settings-dialog";
import type { UserSettings } from "../src/user-settings/types";

const api = vi.hoisted(() => ({
    get: vi.fn<(endpoint: string) => Promise<UserSettings>>(),
    put: vi.fn<(endpoint: string, body: unknown) => Promise<UserSettings>>(),
}));
vi.mock("../src/auth/hooks/use-authenticated-api", () => ({
    useAuthenticatedApi: () => api,
}));
vi.mock("../src/lib/theme-context", () => ({
    useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }),
}));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root | undefined;
let host: HTMLDivElement | undefined;
const settle = async (): Promise<void> =>
    new Promise((resolve) => setTimeout(resolve, 0));

const button = (label: string): HTMLButtonElement => {
    const found = [...document.querySelectorAll("button")].find(
        (item) => item.textContent?.trim() === label,
    );
    assert.ok(found, `Missing button: ${label}`);
    return found;
};
const field = (): HTMLTextAreaElement => {
    const found = document.querySelector<HTMLTextAreaElement>(
        "[role=dialog] textarea",
    );
    assert.ok(found);
    return found;
};
const click = async (label: string): Promise<void> => {
    await act(async () => {
        button(label).click();
        await settle();
    });
};
const enter = async (value: string): Promise<void> => {
    await act(async () => {
        const input = field();
        Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype,
            "value",
        )?.set?.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        await settle();
    });
};

const Harness = () => {
    const [open, setOpen] = useState(false);
    return createElement(
        "div",
        undefined,
        createElement(
            "button",
            { onClick: () => setOpen(true), type: "button" },
            "Settings",
        ),
        open
            ? createElement(UserSettingsDialog, {
                  onClose: () => setOpen(false),
              })
            : undefined,
    );
};
const mount = async (): Promise<void> => {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => {
        root?.render(createElement(Harness));
        await settle();
    });
    await click("Settings");
    await act(settle);
};

beforeEach(() => {
    api.get.mockReset();
    api.put.mockReset();
    api.get.mockResolvedValue({ personal_instructions: "Original context" });
    api.put.mockResolvedValue({ personal_instructions: "I work in Public Health." });
});
afterEach(async () => {
    await act(async () => root?.unmount());
    host?.remove();
    root = undefined;
    host = undefined;
});

test("Save persists personal instructions and reopening reloads the server value", async () => {
    await mount();
    assert.equal(field().value, "Original context");
    assert.ok(button("Save").disabled);
    await enter("I work in Public Health.");
    await click("Save");
    assert.deepEqual(api.put.mock.calls, [
        ["/user-settings", { personal_instructions: "I work in Public Health." }],
    ]);
    assert.equal(document.querySelector("[role=dialog]"), null);
    api.get.mockResolvedValue({ personal_instructions: "I work in Public Health." });
    await click("Settings");
    assert.equal(field().value, "I work in Public Health.");
    assert.equal(api.get.mock.calls.length, 2);
});

test("Cancel discards a draft and clearing the field saves an empty setting", async () => {
    await mount();
    await enter("Unsaved context");
    await click("Cancel");
    assert.equal(api.put.mock.calls.length, 0);
    await click("Settings");
    assert.equal(field().value, "Original context");
    await enter("");
    await click("Save");
    assert.deepEqual(api.put.mock.calls, [
        ["/user-settings", { personal_instructions: "" }],
    ]);
});

test("the counter and validation use Unicode code points just like the API", async () => {
    await mount();
    await enter("🩺".repeat(2000));
    const formattedLimit = formatLocaleNumber(2000);
    assert.ok(
        document
            .querySelector("[role=dialog]")
            ?.textContent?.includes(`${formattedLimit} / ${formattedLimit}`),
    );
    assert.equal(field().getAttribute("aria-invalid"), "false");
    assert.equal(button("Save").disabled, false);
    await enter("🩺".repeat(2001));
    assert.equal(field().value, "🩺".repeat(2001));
    assert.equal(field().getAttribute("aria-invalid"), "true");
    assert.ok(button("Save").disabled);
    const validationError = document.querySelector("[role=alert]");
    assert.ok(
        validationError?.textContent?.includes(`${formattedLimit} characters`),
    );
    assert.equal(
        field().getAttribute("aria-errormessage"),
        validationError?.id,
    );
    assert.equal(api.put.mock.calls.length, 0);
});

test("an in-flight save cannot be duplicated or dismissed and a failure retains the draft", async () => {
    let failSave: ((error: Error) => void) | undefined;
    api.put.mockImplementation(
        () =>
            new Promise((_resolve, reject) => {
                failSave = reject;
            }),
    );
    await mount();
    await enter("Keep this draft");
    await click("Save");
    await click("Save");
    assert.equal(api.put.mock.calls.length, 1);
    assert.ok(button("Cancel").disabled);
    assert.ok(field().disabled);
    await act(async () => {
        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        await settle();
    });
    assert.ok(document.querySelector("[role=dialog]"));
    await act(async () => {
        failSave?.(new Error("Network failed"));
        await settle();
    });
    assert.equal(field().value, "Keep this draft");
    assert.equal(field().disabled, false);
    assert.match(
        document.querySelector("[role=alert]")?.textContent ?? "",
        /Could not save/u,
    );
    api.put.mockResolvedValue({ personal_instructions: "Keep this draft" });
    await click("Save");
    assert.equal(api.put.mock.calls.length, 2);
    assert.equal(document.querySelector("[role=dialog]"), null);
});

test("the dialog shows its final layout, disabled, while the value loads", async () => {
    let resolveLoad: (value: UserSettings) => void = () => undefined;
    api.get.mockReturnValue(
        new Promise<UserSettings>((resolve) => {
            resolveLoad = resolve;
        }),
    );
    await mount();
    assert.ok(field().disabled);
    assert.ok(button("Save").disabled);
    assert.ok(!button("Cancel").disabled);
    await act(async () => {
        resolveLoad({ personal_instructions: "Loaded context" });
        await settle();
    });
    assert.ok(!field().disabled);
    assert.equal(field().value, "Loaded context");
});

test("a failed load cannot overwrite an unknown existing preference", async () => {
    api.get.mockRejectedValue(new Error("Network failed"));
    await mount();
    assert.equal(document.querySelector("[role=dialog] textarea"), null);
    assert.match(
        document.querySelector("[role=alert]")?.textContent ?? "",
        /Could not load/u,
    );
    api.get.mockResolvedValue({ personal_instructions: "Restored context" });
    await click("Try again");
    assert.equal(field().value, "Restored context");
    assert.equal(api.put.mock.calls.length, 0);
});

const permissions: Record<PermissionKey, boolean> = {
    access_chats: false,
    access_investigations: false,
    access_messages: false,
    access_compliance: false,
    edit_compliance_instructions: false,
    access_instructions: false,
    access_traces: false,
    access_rag: false,
    access_rbac: false,
    access_usage: false,
    access_analytics: false,
    access_chat_insights: false,
    run_chat_insights: false,
    manage_chat_insight_categories: false,
    access_adoption: false,
    access_public_analytics: false,
    access_evals: false,
    access_settings: false,
    access_rag_viewer: false,
    access_resources: false,
    access_rag_exclusions: false,
    chat_regenerate: false,
    chat_view_activity: false,
    chat_view_trace: false,
    chat_model_selection: false,
    chat_duration_tooltip: false,
    chat_view_response_cost: false,
    chat_view_guardrails_failures: false,
    chat_view_sources: false,
    chat_view_tools: false,
    chats_view_own: false,
    chats_view_users: false,
    chats_view_admins: false,
    chats_view_devs: false,
    chats_view_trace: false,
    chats_view_cost_column: false,
};
const roles: UserProfile["group"]["slug"][] = ["user", "admin", "dev"];
test.each(roles)(
    "%s can open Settings without access_settings permission",
    async (role) => {
        const user: UserProfile = {
            id: `user-${role}`,
            email: "user@example.com",
            name: "Test User",
            group: { id: "group", slug: role, name: role },
            permissions,
            is_active: true,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
        };
        const onViewChange = vi.fn();
        host = document.createElement("div");
        document.body.append(host);
        root = createRoot(host);
        await act(async () =>
            root?.render(
                createElement(
                    SidebarProvider,
                    { defaultOpen: true },
                    createElement(AppSidebar, {
                        activeView: "chat",
                        onViewChange,
                        onLogout: async () => undefined,
                        user,
                    }),
                ),
            ),
        );
        assert.ok(button("Settings"));
        assert.equal(
            host.textContent?.includes("Developer settings"),
            role === "dev",
        );
        await click("Settings");
        assert.equal(field().value, "Original context");
        assert.equal(onViewChange.mock.calls.length, 0);
    },
);
