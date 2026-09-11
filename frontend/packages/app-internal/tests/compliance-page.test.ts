// @vitest-environment happy-dom
import assert from "node:assert/strict";

import {
    createMemoryHistory,
    createRootRoute,
    createRoute,
    createRouter,
    RouterProvider,
} from "@tanstack/react-router";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, test, vi } from "vitest";

import {
    ComplianceFlagPage,
    ComplianceHomePage,
    ComplianceInstructionsPage,
    CompliancePage,
    ComplianceScreeningPage,
} from "../src/compliance/components/compliance-page";
import { validateComplianceSearch } from "../src/compliance/lib/presentation";
import {
    finding,
    flagDetail,
    flagSummary,
    screening,
} from "./compliance-fixtures";

const api = vi.hoisted(() => ({
    get: vi.fn<(endpoint: string) => Promise<unknown>>(),
    post: vi.fn<(endpoint: string, body: unknown) => Promise<unknown>>(),
}));
vi.mock("../src/auth/hooks/use-authenticated-api", () => ({
    useAuthenticatedApi: () => api,
}));
vi.mock("../src/auth/contexts/auth-context", () => ({
    useAuth: () => ({
        user: {
            group: { slug: "dev" },
            permissions: { edit_compliance_instructions: true },
        },
    }),
}));
// Date selection is independent of these screening/reading lifecycle tests.
vi.mock("../src/components/time-range-filter", () => ({
    TimeRangeFilter: () => undefined,
}));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const base = `/compliance/screenings/${screening.id}`;
const detailUrl = `${base}/flags/${finding.id}`;
const instructionsUrl = "/compliance/instructions?offset=0&limit=25";
const settle = async (): Promise<void> =>
    new Promise((resolve) => setTimeout(resolve, 0));
const button = (label: string): HTMLButtonElement => {
    const found = [...document.querySelectorAll("button")].find(
        (node) =>
            node.getAttribute("aria-label") === label ||
            node.textContent?.trim() === label,
    );
    assert.ok(found, `Missing button: ${label}`);
    return found;
};
const click = async (label: string): Promise<void> => {
    await act(async () => {
        button(label).click();
        await settle();
    });
    await act(settle);
};
const refresh = async (): Promise<void> => {
    await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
        await settle();
    });
    await act(settle);
};
const typeInstructions = async (text: string): Promise<HTMLTextAreaElement> => {
    const textarea = document.querySelector("textarea");
    assert.ok(textarea);
    await act(async () => {
        Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype,
            "value",
        )?.set?.call(textarea, text);
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    return textarea;
};
const mount = async (url: string) => {
    const history = createMemoryHistory({ initialEntries: [url] });
    const rootRoute = createRootRoute();
    const route = createRoute({
        getParentRoute: () => rootRoute,
        path: "/compliance",
        validateSearch: () => ({}),
        component: CompliancePage,
    });
    const homeRoute = createRoute({
        getParentRoute: () => route,
        path: "/",
        component: ComplianceHomePage,
    });
    const instructionsRoute = createRoute({
        getParentRoute: () => route,
        path: "/instructions",
        component: ComplianceInstructionsPage,
    });
    const screeningRoute = createRoute({
        getParentRoute: () => route,
        path: "/screenings/$screeningId",
        validateSearch: validateComplianceSearch,
        component: ComplianceScreeningPage,
    });
    const flagRoute = createRoute({
        getParentRoute: () => route,
        path: "/screenings/$screeningId/flags/$flagId",
        validateSearch: validateComplianceSearch,
        component: ComplianceFlagPage,
    });
    const router = createRouter({
        routeTree: rootRoute.addChildren([
            route.addChildren([
                homeRoute,
                instructionsRoute,
                screeningRoute,
                flagRoute,
            ]),
        ]),
        history,
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => {
        await router.load();
        root.render(createElement(RouterProvider, { router }));
        await settle();
    });
    await act(settle);
    return {
        history,
        host,
        cleanup: async () => {
            await act(async () => root.unmount());
            host.remove();
            history.destroy();
        },
    };
};

beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
});

test("polling failures retain the current flag; access loss removes its evidence", async () => {
    const errors = new Map<string, Error>();
    const detail: typeof flagDetail = {
        ...flagDetail,
        transcript: [
            {
                id: flagDetail.message_id,
                parent_id: null,
                role: "assistant",
                content: finding.evidence,
                created_at: screening.start,
            },
        ],
    };
    api.get.mockImplementation(async (endpoint) => {
        if (errors.has(endpoint)) throw errors.get(endpoint);
        if (endpoint === base) return screening;
        if (endpoint === detailUrl) return detail;
        return { items: [flagSummary], total: 1 };
    });
    const page = await mount(
        `/compliance/screenings/${screening.id}/flags/${finding.id}`,
    );
    try {
        const chat = page.host.querySelector('section[aria-label="Chat"]');
        assert.ok(chat);
        assert.equal(chat.querySelector("mark")?.textContent, finding.evidence);
        assert.equal(chat.querySelectorAll("mark").length, 1);
        assert.equal(
            [...chat.querySelectorAll("h1, h2, h3, h4, h5, h6")].some(
                (heading) => heading.textContent === "Chat",
            ),
            false,
        );

        errors.set(base, new Error("Connection interrupted"));
        errors.set(
            detailUrl,
            Object.assign(new Error("Screening service unavailable"), {
                status: 500,
                detail: "Screening service unavailable",
            }),
        );
        await refresh();
        assert.match(page.host.textContent, /Connection interrupted/u);
        assert.match(page.host.textContent, /Screening service unavailable/u);
        assert.equal(page.host.querySelector("mark")?.textContent, finding.evidence);
        errors.clear();
        await refresh();
        assert.equal(page.host.querySelector("mark")?.textContent, finding.evidence);

        errors.set(
            detailUrl,
            Object.assign(new Error("Outside your chat access"), {
                status: 403,
                detail: "Outside your chat access",
            }),
        );
        await refresh();
        assert.match(page.host.textContent, /Outside your chat access/u);
        assert.equal(page.host.querySelector("mark"), null);
        assert.equal(
            [...page.host.querySelectorAll("button")].some(
                (node) => node.textContent === "Confirm" || node.textContent === "Dismiss",
            ),
            false,
        );
    } finally {
        await page.cleanup();
    }
});

test("view instructions navigates immediately", async () => {
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint === instructionsUrl) {
            return new Promise<never>(() => undefined);
        }
        return { items: [], total: 0 };
    });
    api.post.mockImplementation(async () => ({
        messages: 0,
        conversations: 0,
        max_messages: 10_000,
        instructions: null,
        overlaps: [],
        worker_enabled: true,
    }));
    const page = await mount("/compliance");
    try {
        await click("Instructions");
        assert.equal(page.history.location.pathname, "/compliance/instructions");
        assert.equal(page.history.location.search, "");
        assert.equal(button("Back to screenings").disabled, false);
        assert.equal(
            page.host.querySelector('section[aria-label="Previous screenings"]'),
            null,
        );
    } finally {
        await page.cleanup();
    }
});

test("an instruction conflict preserves and explicitly rebases the draft", async () => {
    const first = screening.instructions;
    const second = {
        ...first,
        id: "77777777-7777-4777-8777-777777777777",
        number: 2,
        author: "Another lawyer",
        content: "Newest saved instructions.",
    };
    const third = {
        ...second,
        id: "88888888-8888-4888-8888-888888888888",
        number: 3,
        author: "Current lawyer",
        content: "My preserved draft.",
    };
    let current = first;
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint === instructionsUrl) {
            return { current, versions: [current], total: 1 };
        }
        throw new Error(`Unexpected GET ${endpoint}`);
    });
    api.post.mockImplementation(async (endpoint) => {
        assert.equal(endpoint, "/compliance/instructions");
        if (api.post.mock.calls.length === 1) {
            current = second;
            throw Object.assign(new Error("409: The saved instructions have changed."), {
                status: 409,
                detail: "The saved instructions have changed.",
            });
        }
        current = third;
        return third;
    });
    const page = await mount("/compliance/instructions");
    try {
        await click("Edit");
        await typeInstructions(third.content);
        await click("Save");

        assert.equal(
            page.host.querySelector("textarea")?.value,
            third.content,
        );
        assert.match(page.host.textContent, /changed while you were editing/u);
        await click("Review latest saved instructions (Version 2)");
        assert.match(page.host.textContent, /Newest saved instructions\./u);
        assert.equal(button("Save").disabled, true);

        await click("Continue with my draft");
        assert.equal(button("Save").disabled, false);
        await click("Save");
        assert.deepEqual(api.post.mock.calls[1]?.[1], {
            base_version_id: second.id,
            content: third.content,
        });
        assert.equal(page.host.querySelector("textarea"), null);
        assert.match(page.host.textContent, /Version 3/u);
    } finally {
        await page.cleanup();
    }
});

test("a deep-linked flag remains reviewable outside the current queue page", async () => {
    const otherFlag = {
        ...flagSummary,
        id: "88888888-8888-4888-8888-888888888888",
    };
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint === base) return screening;
        if (endpoint === detailUrl) return flagDetail;
        return { items: [otherFlag], total: 1 };
    });
    const page = await mount(
        `/compliance/screenings/${screening.id}/flags/${finding.id}`,
    );
    try {
        assert.equal(button("Back to screening").disabled, false);
        assert.ok(document.body.textContent?.includes("Review flag"));
        assert.ok(document.body.textContent?.includes(finding.explanation));
    } finally {
        await page.cleanup();
    }
});

test("flag navigation retains an inert review until the next flag replaces it", async () => {
    const secondEvidence = "Tuition is guaranteed.";
    const reviewTranscript: typeof flagDetail.transcript = [
        {
            id: flagDetail.message_id,
            parent_id: null,
            role: "assistant",
            content: `${finding.evidence} ${secondEvidence}`,
            created_at: screening.start,
        },
    ];
    const firstDetail = { ...flagDetail, transcript: reviewTranscript };
    const secondFinding: typeof finding = {
        ...finding,
        id: "88888888-8888-4888-8888-888888888888",
        title: "Different flag",
        explanation: "A different explanation for the second flag.",
        evidence: secondEvidence,
    };
    const secondSummary = {
        ...flagSummary,
        id: secondFinding.id,
        title: secondFinding.title,
    };
    const secondDetail = {
        ...flagDetail,
        flag: secondFinding,
        transcript: reviewTranscript,
    };
    const secondUrl = `${base}/flags/${secondFinding.id}`;
    let loadSecond: ((detail: typeof secondDetail) => void) | undefined;
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint === base) return screening;
        if (endpoint === detailUrl) return firstDetail;
        if (endpoint === secondUrl) {
            return new Promise<typeof secondDetail>((resolve) => {
                loadSecond = resolve;
            });
        }
        return { items: [flagSummary, secondSummary], total: 2 };
    });
    api.post.mockResolvedValue({
        state: "confirmed",
        reviewer: "Current lawyer",
        created_at: screening.created_at,
        revision: 1,
    });
    const page = await mount(detailUrl);
    try {
        assert.ok(page.host.querySelector('section[aria-label="Flag review"]'));
        assert.equal(page.host.querySelector("mark")?.textContent, finding.evidence);
        await click("Confirm");
        assert.match(page.host.textContent, /Confirmed by Current lawyer/u);
        await click("Next flag");

        assert.equal(page.history.location.pathname, secondUrl);
        const pendingReview = page.host.querySelector(
            'section[aria-label="Flag review"]',
        );
        assert.ok(pendingReview);
        assert.equal(pendingReview.getAttribute("aria-busy"), "true");
        assert.equal(pendingReview.hasAttribute("inert"), true);
        assert.match(page.host.textContent, new RegExp(finding.explanation, "u"));
        assert.equal(page.host.querySelector("mark")?.textContent, finding.evidence);
        assert.ok(loadSecond);
        await act(async () => loadSecond?.(secondDetail));
        const loadedReview = page.host.querySelector(
            'section[aria-label="Flag review"]',
        );
        assert.ok(loadedReview);
        assert.equal(loadedReview.getAttribute("aria-busy"), "false");
        assert.match(page.host.textContent, /A different explanation/u);
        assert.doesNotMatch(
            page.host.textContent,
            new RegExp(finding.explanation, "u"),
        );
        assert.doesNotMatch(page.host.textContent, /Confirmed by Current lawyer/u);
        assert.equal(page.host.querySelector("mark")?.textContent, secondEvidence);
        assert.equal(button("Confirm").disabled, false);
    } finally {
        await page.cleanup();
    }
});

test("failed Chats show actionable reasons and retry only when useful", async () => {
    const failed = {
        ...screening,
        screened: 7,
        screened_conversations: 3,
        errors: 3,
        error_conversations: 2,
        failures: [
            {
                chat_id: "77777777-7777-4777-8777-777777777777",
                chat: "Provider failure",
                assistant_messages: 1,
                reason: "The screening service could not finish this Chat.",
                retryable: true,
            },
            {
                chat_id: "88888888-8888-4888-8888-888888888888",
                chat: "Long Chat",
                assistant_messages: 2,
                reason: "This Chat is too long to screen without leaving out context. Review it manually.",
                retryable: false,
            },
        ],
    };
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint === base) return failed;
        return { items: [], total: 0 };
    });
    api.post.mockResolvedValue({ queued: 1, conversations: 1 });
    const page = await mount(`/compliance/screenings/${screening.id}`);
    try {
        assert.match(page.host.textContent, /2 Chats could not be screened/u);
        assert.match(page.host.textContent, /Provider failure/u);
        assert.match(page.host.textContent, /Long Chat/u);
        assert.match(page.host.textContent, /Review it manually/u);
        await click("Retry");
        assert.deepEqual(api.post.mock.calls[0], [
            `/compliance/screenings/${screening.id}/retry`,
            {},
        ]);
    } finally {
        await page.cleanup();
    }
});

test("a scheduled admission failure stays visible without a futile retry", async () => {
    const reason =
        "Too many assistant messages were eligible for this scheduled screening. Start separate manual screenings for shorter periods.";
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint === base) {
            return {
                ...screening,
                admission_error: reason,
                messages: 0,
                conversations: 0,
                screened: 0,
                screened_conversations: 0,
                findings: 0,
                needs_review: 0,
            };
        }
        return { items: [], total: 0 };
    });
    const page = await mount(`/compliance/screenings/${screening.id}`);
    try {
        assert.match(page.host.textContent, /Too many assistant messages/u);
        assert.match(page.host.textContent, /Incomplete/u);
        assert.equal(
            [...page.host.querySelectorAll("button")].some(
                (candidate) => candidate.textContent?.trim() === "Retry",
            ),
            false,
        );
    } finally {
        await page.cleanup();
    }
});

test("active screenings show chat-level progress", async () => {
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint === base) {
            return {
                ...screening,
                screened: 4,
                screened_conversations: 2,
                pending: 6,
            };
        }
        return { items: [flagSummary], total: 1 };
    });
    const page = await mount(`/compliance/screenings/${screening.id}`);
    try {
        const progress = document.querySelector('[role="progressbar"]');
        assert.ok(progress);
        assert.equal(progress.getAttribute("aria-valuenow"), "40");
        assert.ok(document.body.textContent?.includes("2 of 5 chats"));
    } finally {
        await page.cleanup();
    }
});

test("screenings present one flag queue with a primary next action", async () => {
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint === base) return screening;
        if (endpoint === detailUrl) return flagDetail;
        return { items: [flagSummary], total: 1 };
    });
    const page = await mount(`/compliance/screenings/${screening.id}`);
    try {
        assert.equal(page.history.location.search, "");
        assert.equal(button("Back to screenings").disabled, false);
        assert.equal(button("Review next").disabled, false);
        assert.deepEqual(
            [...document.querySelectorAll("th")].map(
                (header) => header.textContent,
            ),
            ["Flag", "Chat", "Message", "Decision"],
        );
        const rowActionLabel = `Review flag: ${finding.title}`;
        assert.equal(button(rowActionLabel).tagName, "BUTTON");
        await click(rowActionLabel);
        assert.equal(page.history.location.pathname, detailUrl);
    } finally {
        await page.cleanup();
    }
});

test("rolling screening periods use the time the dialog opens", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const firstOpen = new Date("2026-09-02T12:00:00Z");
    const secondOpen = new Date("2026-09-03T12:00:00Z");
    vi.setSystemTime(firstOpen);
    api.get.mockResolvedValue({ items: [], total: 0 });
    api.post.mockResolvedValue({
        messages: 10,
        conversations: 5,
        max_messages: 10_000,
        instructions: screening.instructions,
        overlaps: [],
        worker_enabled: true,
    });
    const page = await mount("/compliance");
    try {
        await click("New");
        const firstPreview = api.post.mock.calls.findLast(
            ([endpoint]) => endpoint === "/compliance/screenings/preview",
        );
        assert.ok(firstPreview);
        assert.equal((firstPreview[1] as { end: string }).end, firstOpen.toISOString());
        await click("Close");

        vi.setSystemTime(secondOpen);
        await click("New");
        const secondPreview = api.post.mock.calls.findLast(
            ([endpoint]) => endpoint === "/compliance/screenings/preview",
        );
        assert.ok(secondPreview);
        assert.equal(
            (secondPreview[1] as { end: string }).end,
            secondOpen.toISOString(),
        );
    } finally {
        await page.cleanup();
        vi.useRealTimers();
    }
});

test("overlap confirmation stays inside the new-screening modal", async () => {
    api.get.mockResolvedValue({ items: [], total: 0 });
    api.post.mockImplementation(async (endpoint) => {
        if (endpoint === "/compliance/screenings/preview") {
            return {
                messages: 10,
                conversations: 5,
                max_messages: 10_000,
                instructions: screening.instructions,
                overlaps: [
                    {
                        id: screening.id,
                        created_at: screening.created_at,
                    },
                ],
                worker_enabled: true,
            };
        }
        if (endpoint === "/compliance/screenings") {
            return screening;
        }
        throw new Error(`Unexpected POST ${endpoint}`);
    });
    const page = await mount("/compliance");
    try {
        assert.deepEqual(
            [...document.querySelectorAll("th")].map(
                (header) => header.textContent,
            ),
            ["Period", "Status", "Flags", "Reviewed"],
        );
        await click("New");
        assert.equal(document.querySelectorAll('[role="dialog"]').length, 1);
        await click("Start screening");
        assert.ok(
            document.body.textContent?.includes("Screen this period again?"),
        );
        assert.equal(document.querySelectorAll('[role="dialog"]').length, 1);
        assert.equal(document.querySelector('[role="alertdialog"]'), null);
        await click("Start separate screening");
        const started = api.post.mock.calls.find(
            ([endpoint]) => endpoint === "/compliance/screenings",
        );
        assert.ok(started);
        assert.equal(
            (started[1] as { acknowledge_overlap: boolean })
                .acknowledge_overlap,
            true,
        );
        assert.equal(
            page.history.location.pathname,
            `/compliance/screenings/${screening.id}`,
        );
    } finally {
        await page.cleanup();
    }
});

test("the new-screening modal waits for a current preview", async () => {
    const updated = {
        ...screening.instructions,
        id: "77777777-7777-4777-8777-777777777777",
        number: 2,
        content: "Screen for updated requirements.",
    };
    const preview = (instructions: typeof screening.instructions) => ({
        messages: 10,
        conversations: 5,
        max_messages: 10_000,
        instructions,
        overlaps: [],
        worker_enabled: true,
    });
    let releasePreview: (() => void) | undefined;
    api.get.mockImplementation(async (endpoint) => {
        if (endpoint.startsWith("/compliance/instructions")) {
            return {
                current: screening.instructions,
                versions: [screening.instructions],
                total: 1,
            };
        }
        if (endpoint === base) {
            return { ...screening, instructions: updated };
        }
        return { items: [], total: 0 };
    });
    api.post.mockImplementation(async (endpoint) => {
        if (endpoint === "/compliance/screenings/preview") {
            return new Promise((resolve) => {
                releasePreview = () => {
                    resolve(preview(updated));
                };
            });
        }
        if (endpoint === "/compliance/instructions") {
            return updated;
        }
        if (endpoint === "/compliance/screenings") {
            return { ...screening, instructions: updated };
        }
        throw new Error(`Unexpected POST ${endpoint}`);
    });
    const page = await mount("/compliance");
    try {
        assert.equal(
            api.post.mock.calls.some(
                ([endpoint]) => endpoint === "/compliance/screenings/preview",
            ),
            false,
        );
        assert.ok(!document.body.textContent?.includes("Start screening"));
        await click("Instructions");
        await click("Edit");
        await typeInstructions(updated.content);
        await click("Save");
        await click("Back to screenings");
        assert.ok(!document.body.textContent?.includes("Start screening"));

        await click("New");
        assert.ok(releasePreview);
        assert.equal(button("Start screening").disabled, true);
        assert.equal(
            api.post.mock.calls.some(
                ([endpoint]) => endpoint === "/compliance/screenings",
            ),
            false,
        );

        await act(async () => {
            releasePreview?.();
            await settle();
        });
        assert.equal(button("Start screening").disabled, false);
        await click("Start screening");
        assert.equal(
            page.history.location.pathname,
            `/compliance/screenings/${screening.id}`,
        );
        assert.equal(page.history.location.search, "");
        const started = api.post.mock.calls.find(
            ([endpoint]) => endpoint === "/compliance/screenings",
        );
        assert.ok(started);
        assert.equal(
            (started[1] as { instructions_version_id: string })
                .instructions_version_id,
            updated.id,
        );
    } finally {
        await page.cleanup();
    }
});
