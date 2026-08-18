import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    convertConversationTree,
    createLatestRequestCoordinator,
    hasConversationBranches,
    hasMessageBranchAlternatives,
} from "../src/chat/lib/conversation-tree.ts";

describe("conversation tree projection", () => {
    it("preserves ordered roots, children, and the canonical path", () => {
        const tree = convertConversationTree({
            messages: [
                {
                    id: "root-a",
                    role: "user",
                    content: "First root",
                    parent_id: null,
                },
                {
                    id: "answer-a",
                    role: "assistant",
                    content: "First answer",
                    parent_id: "root-a",
                },
                {
                    id: "answer-b",
                    role: "assistant",
                    content: "Alternate answer",
                    parent_id: "root-a",
                },
                {
                    id: "root-b",
                    role: "user",
                    content: "Alternate root",
                    parent_id: null,
                },
            ],
            current_branch_path: ["root-a", "answer-b"],
        });

        assert.deepEqual(tree.rootMessageIds, ["root-a", "root-b"]);
        assert.deepEqual(tree.childrenByParent.get("root-a"), [
            "answer-a",
            "answer-b",
        ]);
        assert.deepEqual(tree.currentBranchPath, ["root-a", "answer-b"]);
        assert.equal(tree.messagesById.get("answer-b")?.parentId, "root-a");
        assert.equal(hasConversationBranches(tree), true);
        assert.equal(hasMessageBranchAlternatives(tree, "root-a"), true);
        assert.equal(hasMessageBranchAlternatives(tree, "answer-a"), true);
        assert.equal(hasMessageBranchAlternatives(tree, "missing"), false);
    });
});

describe("latest request coordination", () => {
    it("marks an older request stale after a newer request starts", async () => {
        const requests = createLatestRequestCoordinator();
        const older = Promise.withResolvers<string>();
        const olderResult = requests.run(async () => older.promise);

        assert.deepEqual(await requests.run(async () => "newer"), {
            status: "current",
            value: "newer",
        });

        older.resolve("older");
        assert.deepEqual(await olderResult, { status: "stale" });
    });

    it("marks an invalidated request stale without surfacing its late failure", async () => {
        const requests = createLatestRequestCoordinator();
        const deferred = Promise.withResolvers<string>();
        const result = requests.run(async () => deferred.promise);

        requests.invalidate();
        deferred.reject(new Error("late failure"));

        assert.deepEqual(await result, { status: "stale" });
    });

    it("propagates a failure from the current request", async () => {
        const requests = createLatestRequestCoordinator();
        const requestError = new Error("current failure");

        await assert.rejects(
            requests.run(async () => {
                throw requestError;
            }),
            (error: unknown) => error === requestError,
        );
    });
});
