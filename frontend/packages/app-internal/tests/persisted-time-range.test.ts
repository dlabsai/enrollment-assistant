// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, test } from "vitest";

import { usePersistedTimeRange } from "../src/lib/hooks/use-persisted-time-range";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const storageKey = "test-persisted-time-range";
const customStart = new Date("2026-08-10T09:15:00.000Z");
const customEnd = new Date("2026-08-12T16:45:59.999Z");

const TimeRangeProbe = (): React.JSX.Element => {
    const {
        timeRange,
        customRange,
        setTimeRange,
        setCustomRange,
        resetTimeRange,
    } = usePersistedTimeRange(storageKey, "90d");

    return createElement(
        "div",
        {},
        createElement(
            "output",
            {},
            [
                timeRange,
                customRange.start?.toISOString() ?? "no start",
                customRange.end?.toISOString() ?? "no end",
            ].join(" | "),
        ),
        createElement(
            "button",
            {
                onClick: () => {
                    setCustomRange({ start: customStart, end: customEnd });
                    setTimeRange("custom");
                },
            },
            "Use custom range",
        ),
        createElement(
            "button",
            { onClick: () => setTimeRange("60d") },
            "Use 60 days",
        ),
        createElement("button", { onClick: resetTimeRange }, "Clear"),
    );
};

interface MountedProbe {
    host: HTMLDivElement;
    root: Root;
}

const mountProbe = async (): Promise<MountedProbe> => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(() => root.render(createElement(TimeRangeProbe)));
    return { host, root };
};

const unmountProbe = async ({ host, root }: MountedProbe): Promise<void> => {
    await act(() => root.unmount());
    host.remove();
};

const clickButton = async (
    host: HTMLElement,
    label: string,
): Promise<void> => {
    const button = [...host.querySelectorAll("button")].find(
        (candidate) => candidate.textContent === label,
    );
    assert.ok(button);
    await act(() => button.click());
};

beforeEach(() => {
    window.localStorage.clear();
});

test("the selected range survives remounting and Clear restores the default", async () => {
    let mounted: MountedProbe | undefined;
    const remount = async (): Promise<MountedProbe> => {
        if (mounted !== undefined) {
            const previous = mounted;
            mounted = undefined;
            await unmountProbe(previous);
        }
        mounted = await mountProbe();
        return mounted;
    };

    try {
        let current = await remount();
        assert.equal(
            current.host.querySelector("output")?.textContent,
            "90d | no start | no end",
        );

        await clickButton(current.host, "Use custom range");
        current = await remount();
        assert.equal(
            current.host.querySelector("output")?.textContent,
            "custom | 2026-08-10T09:15:00.000Z | 2026-08-12T16:45:59.999Z",
        );

        await clickButton(current.host, "Use 60 days");
        current = await remount();
        assert.match(
            current.host.querySelector("output")?.textContent ?? "",
            /^60d \|/u,
        );

        await clickButton(current.host, "Clear");
        current = await remount();
        assert.equal(
            current.host.querySelector("output")?.textContent,
            "90d | no start | no end",
        );
    } finally {
        if (mounted !== undefined) {
            await unmountProbe(mounted);
        }
    }
});
