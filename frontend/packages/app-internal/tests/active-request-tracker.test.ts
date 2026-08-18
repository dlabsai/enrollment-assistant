import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createActiveRequestTracker } from "../src/chat/lib/active-request-tracker.ts";

describe("active request tracking", () => {
    it("keeps an older request stale after a newer request finishes", () => {
        const tracker = createActiveRequestTracker();
        const older = tracker.start("chat-1");
        const newer = tracker.start("chat-1");

        assert.equal(older.isCurrent(), false);
        assert.equal(newer.isCurrent(), true);

        newer.finish();

        assert.equal(older.isCurrent(), false);
        assert.equal(newer.isCurrent(), false);
    });

    it("moves current request ownership from a temporary key to its conversation id", () => {
        const tracker = createActiveRequestTracker();
        const request = tracker.start("__temp_1");

        request.moveTo("chat-1");

        assert.equal(request.isCurrent(), true);

        const replacement = tracker.start("chat-1");
        assert.equal(replacement.isCurrent(), true);
        assert.equal(request.isCurrent(), false);
    });

    it("reports when a destination already belongs to a newer request", () => {
        const tracker = createActiveRequestTracker();
        const temporaryRequest = tracker.start("__temp_1");
        const destinationRequest = tracker.start("chat-1");

        assert.equal(temporaryRequest.moveTo("chat-1"), false);
        assert.equal(temporaryRequest.isCurrent(), false);
        assert.equal(destinationRequest.isCurrent(), true);
    });

    it("does not let a stale request take ownership while moving keys", () => {
        const tracker = createActiveRequestTracker();
        const stale = tracker.start("__temp_1");
        const current = tracker.start("__temp_1");

        assert.equal(stale.moveTo("chat-1"), false);
        assert.equal(current.moveTo("chat-1"), true);

        assert.equal(stale.isCurrent(), false);
        assert.equal(current.isCurrent(), true);
    });

    it("invalidates the request for an aborted conversation", () => {
        const tracker = createActiveRequestTracker();
        const request = tracker.start("chat-1");

        tracker.invalidate("chat-1");

        assert.equal(request.isCurrent(), false);
    });
});
