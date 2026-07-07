import { isRecord } from "@va/shared/lib/type-guards";

import type { MessageGuardrailsFailure } from "../types";

interface ServerGuardrailsFailure {
    assistant_message: string;
    llm_guardrails_feedback?: string | null;
    invalid_urls?: string[] | null;
}

const toGuardrailsFailure = (
    failure: ServerGuardrailsFailure,
): MessageGuardrailsFailure => ({
    assistantMessage: failure.assistant_message,
    llmGuardrailsFeedback: failure.llm_guardrails_feedback ?? undefined,
    invalidUrls: failure.invalid_urls ?? undefined,
});

export const mapServerGuardrailsFailures = (
    failures: ServerGuardrailsFailure[] | null | undefined,
): MessageGuardrailsFailure[] | undefined =>
    failures === undefined || failures === null
        ? undefined
        : failures.map((failure) => toGuardrailsFailure(failure));

export const parseServerGuardrailsFailures = (
    value: unknown,
): MessageGuardrailsFailure[] | undefined => {
    if (!Array.isArray(value)) {
        return undefined;
    }

    const failures = value.flatMap((item): MessageGuardrailsFailure[] => {
        if (!isRecord(item) || typeof item.assistant_message !== "string") {
            return [];
        }
        return [
            toGuardrailsFailure({
                assistant_message: item.assistant_message,
                llm_guardrails_feedback:
                    typeof item.llm_guardrails_feedback === "string"
                        ? item.llm_guardrails_feedback
                        : undefined,
                invalid_urls: Array.isArray(item.invalid_urls)
                    ? item.invalid_urls.filter(
                          (url): url is string => typeof url === "string",
                      )
                    : undefined,
            }),
        ];
    });

    return failures.length > 0 ? failures : undefined;
};
