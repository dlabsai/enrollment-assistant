import { getResolvedSpanTiming, getStringAttribute } from "../lib/trace-utils";
import type { TraceSpan } from "../types";

export interface SpanSectionMeta {
    span: TraceSpan;
    title: string;
    subtitle: string | undefined;
}

export const buildSpanSections = (spans: TraceSpan[]): SpanSectionMeta[] => {
    const ordered = spans
        .map((span, index) => ({ span, index }))
        .toSorted((left, right) => {
            const leftStart = getResolvedSpanTiming(left.span).start ?? 0;
            const rightStart = getResolvedSpanTiming(right.span).start ?? 0;
            if (leftStart === rightStart) {
                return left.index - right.index;
            }
            return leftStart - rightStart;
        })
        .map((item) => item.span);

    let chatbotCount = 0;
    let guardrailsCount = 0;
    let searchCount = 0;

    return ordered.map((span) => {
        const attributes = span.attributes ?? {};
        const agentName = getStringAttribute(attributes, "gen_ai.agent.name");
        let title = span.name;
        switch (agentName) {
            case "chatbot": {
                chatbotCount += 1;
                title = `Chatbot Attempt #${chatbotCount}`;
                break;
            }
            case "guardrails": {
                guardrailsCount += 1;
                title = `Guardrails #${guardrailsCount}`;
                break;
            }
            case "search": {
                searchCount += 1;
                title = searchCount > 1 ? `Search #${searchCount}` : "Search";
                break;
            }
            default: {
                if (agentName !== undefined && agentName.trim() !== "") {
                    title = agentName.replaceAll("_", " ");
                }
                break;
            }
        }

        const model = getStringAttribute(attributes, "gen_ai.request.model");
        const subtitleParts = [
            title === span.name ? undefined : span.name,
            model,
        ].filter(
            (value): value is string =>
                typeof value === "string" && value.trim() !== "",
        );
        const subtitleValue = subtitleParts.join(" · ");
        const subtitle =
            subtitleValue.trim() === "" ? undefined : subtitleValue;

        return {
            span,
            title,
            subtitle,
        };
    });
};
