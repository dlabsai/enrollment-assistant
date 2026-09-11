import assert from "node:assert/strict";

import { afterEach, test, vi } from "vitest";

import type { AuthenticatedApi } from "../src/auth/hooks/use-authenticated-api";
import {
    formatExportDate,
    getExportFormatSettings,
} from "../src/lib/file-export";
import {
    createDateInTimeZone,
    getAppFormatMode,
    getAppFormatSettings,
    setAppFormatMode,
} from "../src/lib/time-zone";

const stubStoredMode = (initialMode: string): (() => string) => {
    let storedMode = initialMode;
    vi.stubGlobal("window", {
        localStorage: {
            getItem: () => storedMode,
            setItem: (_key: string, value: string) => {
                storedMode = value;
            },
        },
    });
    return () => storedMode;
};

afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
});

test("Browser mode uses the runtime locale and IANA time zone", () => {
    const browserSettings = new Intl.DateTimeFormat().resolvedOptions();

    assert.equal(getAppFormatMode(), "browser");
    assert.deepEqual(getAppFormatSettings(), {
        locale: browserSettings.locale,
        mode: "browser",
        timeZone: browserSettings.timeZone || "UTC",
    });
});

test("Eastern Time mode persists en-US and America/New_York formatting", () => {
    const getStoredMode = stubStoredMode("eastern");

    assert.deepEqual(getAppFormatSettings(), {
        locale: "en-US",
        mode: "eastern",
        timeZone: "America/New_York",
    });
    assert.deepEqual(getExportFormatSettings(), {
        locale: "en-US",
        timeZone: "America/New_York",
    });
    assert.equal(
        formatExportDate(new Date("2026-01-01T02:30:00.000Z")),
        "2025-12-31",
    );

    setAppFormatMode("browser");
    assert.equal(getStoredMode(), "browser");
});

test("Eastern wall-clock conversion follows daylight-saving transitions", () => {
    const eastern = "America/New_York";

    assert.equal(
        createDateInTimeZone(eastern, 2026, 1, 15, 12).toISOString(),
        "2026-01-15T17:00:00.000Z",
    );
    assert.equal(
        createDateInTimeZone(eastern, 2026, 7, 15, 12).toISOString(),
        "2026-07-15T16:00:00.000Z",
    );
    assert.equal(
        createDateInTimeZone(eastern, 2026, 3, 8, 2, 30).toISOString(),
        "2026-03-08T07:30:00.000Z",
    );
    assert.equal(
        createDateInTimeZone(eastern, 2026, 11, 1, 1, 30).toISOString(),
        "2026-11-01T05:30:00.000Z",
    );
});

test("Eastern formatting applies to visible values and local analytics", async () => {
    stubStoredMode("eastern");
    vi.resetModules();
    const { fetchAdoptionSummary } = await import("../src/adoption/lib/api");
    const { fetchChatAnalyticsSummary } =
        await import("../src/chat-analytics/lib/api");
    const { formatTableTimestamp } = await import("../src/lib/date-format");
    const { formatLocaleNumber, formatUsdCost } =
        await import("../src/lib/number-format");
    const value = new Date("2026-01-01T02:30:00.000Z");
    const expected = new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "America/New_York",
    }).format(value);

    assert.equal(formatTableTimestamp(value), expected);
    assert.equal(formatLocaleNumber(1234.5), "1,234.5");
    assert.equal(formatUsdCost(1234.5), "$1,234.50");

    const endpoints: string[] = [];
    const api = {
        get: async <T>(requestedEndpoint: string): Promise<T> => {
            endpoints.push(requestedEndpoint);
            return {} as T;
        },
    } satisfies Pick<AuthenticatedApi, "get">;
    await fetchAdoptionSummary(api as AuthenticatedApi, "30d", {});
    await fetchChatAnalyticsSummary(api as AuthenticatedApi, "both", "30d", {});

    assert.equal(endpoints.length, 2);
    for (const endpoint of endpoints) {
        assert.equal(
            new URL(endpoint, "http://testserver").searchParams.get(
                "browser_time_zone",
            ),
            "America/New_York",
        );
    }
});
