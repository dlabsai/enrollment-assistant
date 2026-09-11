// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { test, vi } from "vitest";

import { useComplianceData } from "../src/compliance/hooks/use-compliance-data";

type Payload = { value: number };
const Probe = ({
    load,
    enabled = true,
}: {
    load: (signal: AbortSignal) => Promise<Payload>;
    enabled?: boolean;
}): React.JSX.Element => {
    const result = useComplianceData({
        load,
        enabled,
        errorMessage: "Could not load",
    });
    return createElement(
        "div",
        {},
        result.loading ? "Loading" : (result.error ?? "Ready"),
        result.data &&
            createElement(
                "button",
                { onClick: result.refresh },
                String(result.data.value),
            ),
    );
};

test("polling preserves focus and data while loading; changes and access errors update", async () => {
    vi.useFakeTimers();
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    let value = 1;
    let denied = false;
    let pending: Promise<void> | undefined;
    const load = async (): Promise<Payload> => {
        await pending;
        if (denied) {
            throw Object.assign(new Error("Access denied"), {
                status: 403,
                detail: "Access denied",
            });
        }
        return { value };
    };
    try {
        await act(async () => root.render(createElement(Probe, { load })));
        const button = host.querySelector("button");
        assert.ok(button);
        button.focus();
        await act(async () => vi.advanceTimersByTimeAsync(10000));
        assert.equal(host.textContent, "Ready1");
        assert.equal(document.activeElement, button);
        let release: (() => void) | undefined;
        pending = new Promise((resolve) => {
            release = resolve;
        });
        value = 2;
        await act(async () => vi.advanceTimersByTimeAsync(5000));
        assert.equal(host.textContent, "Ready1");
        assert.equal(document.activeElement, button);
        await act(async () => release?.());
        assert.equal(host.textContent, "Ready2");
        assert.equal(document.activeElement?.textContent, "2");
        denied = true;
        await act(async () => vi.advanceTimersByTimeAsync(5000));
        assert.equal(host.textContent, "Access denied");
        assert.equal(host.querySelector("button"), null);
    } finally {
        await act(async () => root.unmount());
        host.remove();
        vi.useRealTimers();
    }
});

test("re-enabling a request waits for fresh data", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    let calls = 0;
    let complete: ((value: Payload) => void) | undefined;
    const load = async (): Promise<Payload> => {
        calls += 1;
        if (calls === 1) {
            return { value: 1 };
        }
        return new Promise((resolve) => {
            complete = resolve;
        });
    };
    try {
        await act(async () =>
            root.render(createElement(Probe, { load })),
        );
        assert.equal(host.textContent, "Ready1");

        await act(async () =>
            root.render(createElement(Probe, { load, enabled: false })),
        );
        assert.equal(host.textContent, "Ready");

        await act(async () =>
            root.render(createElement(Probe, { load })),
        );
        assert.equal(host.textContent, "Loading");
        assert.ok(complete);
        await act(async () => complete?.({ value: 2 }));
        assert.equal(host.textContent, "Ready2");
    } finally {
        await act(async () => root.unmount());
        host.remove();
    }
});

test("changing a request aborts old reads and cannot display its late response", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    let complete: ((value: Payload) => void) | undefined;
    const oldLoad = (): Promise<Payload> => {
        return new Promise((resolve) => {
            complete = resolve;
        });
    };
    const newLoad = async (): Promise<Payload> => ({ value: 2 });
    try {
        await act(async () =>
            root.render(createElement(Probe, { load: oldLoad })),
        );
        assert.equal(host.textContent, "Loading");
        await act(async () =>
            root.render(createElement(Probe, { load: newLoad })),
        );
        assert.ok(complete);
        await act(async () => complete?.({ value: 1 }));
        assert.equal(host.textContent, "Ready2");
    } finally {
        await act(async () => root.unmount());
        host.remove();
    }
});
