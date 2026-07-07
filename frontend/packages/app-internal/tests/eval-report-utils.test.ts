import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    buildModelRoleMap,
    buildOverallAverages,
    buildReportSummaryMetrics,
    buildScoreSummaryRows,
    formatEvalAudience,
    parseModelConfigurations,
    parseSummaryTable,
} from "../src/evals/lib/report-utils.ts";
import type { EvalReportDetail } from "../src/evals/types/index.ts";

const report: EvalReportDetail = {
    id: "eval-demo-va-chatbot-eval-20260427-120000-000000",
    title: "Demo VA Chatbot Eval",
    name: "demo_va_chatbot_eval",
    suite: "chatbot",
    generatedAt: "2026-04-27T12:00:00Z",
    repeats: 1,
    concurrency: 2,
    passThreshold: 0.9,
    status: "threshold_failed",
    caseCount: 2,
    runCount: 2,
    isInternal: true,
    config: {},
    additionalSettings: {},
    modelConfigs: {
        chatbot_model: {
            model: "azure/gpt-5.5",
            temperature: null,
            max_tokens: 0,
        },
    },
    cases: [
        {
            name: "case_a",
            inputs: { user_input: "hi" },
            expectedOutput: null,
            metadata: null,
            stats: {
                runs: 1,
                assertion_pass_rates: { passed: 1, grounded: 0 },
                pass_rate: 1,
                runtime_error_rate: 0,
                duration_min: 1,
                duration_median: 1.2,
                duration_max: 1.5,
                score_means: { guardrail_retries: 2 },
                score_mins: { guardrail_retries: 1 },
                score_medians: { guardrail_retries: 2 },
                score_maxs: { guardrail_retries: 3 },
            },
            runs: [],
        },
        {
            name: "case_b",
            inputs: { user_input: "programs" },
            expectedOutput: null,
            metadata: null,
            stats: {
                runs: 1,
                assertion_pass_rates: { passed: 0 },
                pass_rate: 0,
                runtime_error_rate: 0,
                duration_min: 2,
                duration_median: 2.4,
                duration_max: 3,
                score_means: { guardrail_retries: 0 },
                score_mins: { guardrail_retries: 0 },
                score_medians: { guardrail_retries: 0 },
                score_maxs: { guardrail_retries: 0 },
            },
            runs: [],
        },
    ],
};

describe("eval report utilities", () => {
    it("builds summary metrics from structured report data", () => {
        assert.deepEqual(parseSummaryTable(report), [
            {
                caseName: "case_a",
                runs: 1,
                passRate: 1,
                runtimeErrorRate: 0,
                durationMin: 1,
                durationMedian: 1.2,
                durationMax: 1.5,
                assertions: "✓ passed: 100%, ✗ grounded: 0%",
            },
            {
                caseName: "case_b",
                runs: 1,
                passRate: 0,
                runtimeErrorRate: 0,
                durationMin: 2,
                durationMedian: 2.4,
                durationMax: 3,
                assertions: "✗ passed: 0%",
            },
        ]);

        const metrics = buildReportSummaryMetrics(report);
        assert.equal(metrics.passRateAverage, 0.5);
        assert.ok(metrics.durationMedianAverage !== undefined);
        assert.ok(Math.abs(metrics.durationMedianAverage - 1.8) < 0.0001);

        assert.deepEqual(buildScoreSummaryRows(report), [
            {
                caseName: "case_a",
                scoreName: "guardrail_retries",
                min: 1,
                median: 2,
                max: 3,
            },
            {
                caseName: "case_b",
                scoreName: "guardrail_retries",
                min: 0,
                median: 0,
                max: 0,
            },
        ]);

        assert.deepEqual(buildOverallAverages(report), {
            assertions: [
                { name: "passed", average: 0.5 },
                { name: "grounded", average: 0 },
            ],
            scores: [{ name: "guardrail_retries", average: 1 }],
        });
    });

    it("formats audience metadata", () => {
        assert.equal(formatEvalAudience(report.isInternal), "Internal VA");
        assert.equal(formatEvalAudience(false), "Public VA");
        assert.equal(formatEvalAudience(null), "Mixed/unknown");
    });

    it("builds model views from structured model config data", () => {
        assert.deepEqual(parseModelConfigurations(report), [
            {
                role: "chatbot_model",
                model: "azure/gpt-5.5",
                temperature: undefined,
                maxTokens: 0,
            },
        ]);

        assert.deepEqual(buildModelRoleMap(report), {
            chatbot: "azure/gpt-5.5",
        });
    });
});
