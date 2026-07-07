import { Badge } from "@va/shared/components/ui/badge";
import { type JSX, memo, useMemo } from "react";

import type { TraceMessage, TraceMessagePart } from "../lib/trace-utils";
import type { TraceSpan } from "../types";
import { ContentValue } from "./trace-turn-content";
import { buildMessagePartKey } from "./trace-turn-message-utils";
import { buildSpanDetailModel } from "./trace-turn-span-model";

interface SpanSectionProps {
    span: TraceSpan;
    traceStart: number | undefined;
    traceEnd: number | undefined;
    title: string;
    subtitle: string | undefined;
    anchorId: string;
    isSelected: boolean;
}

const renderMessagePart = (part: TraceMessagePart): JSX.Element => (
    <div
        className="space-y-1"
        key={buildMessagePartKey(part)}
    >
        <div className="text-muted-foreground text-xs uppercase">
            {part.type}
        </div>
        <ContentValue value={part.raw} />
    </div>
);

const renderMessageContent = (message: TraceMessage): JSX.Element => {
    const parts = message.parts ?? [];
    if (parts.length === 0) {
        return <ContentValue value={message.content} />;
    }

    return (
        <div className="space-y-2">
            {parts.map((part) => renderMessagePart(part))}
        </div>
    );
};

const Section = ({
    title,
    children,
}: {
    title: string;
    children: JSX.Element;
}): JSX.Element => (
    <section className="space-y-2">
        <h4 className="text-sm font-semibold">{title}</h4>
        {children}
    </section>
);

const renderEntryGrid = (
    entries: { label: string; value: string }[],
    columns: string,
): JSX.Element | undefined =>
    entries.length > 0 ? (
        <div className={`grid grid-cols-1 gap-2 text-sm ${columns}`}>
            {entries.map((entry) => (
                <div
                    className="space-y-1"
                    key={entry.label}
                >
                    <div className="text-xs font-semibold">{entry.label}</div>
                    <div className="text-sm">{entry.value}</div>
                </div>
            ))}
        </div>
    ) : undefined;

const renderListSection = <T,>(
    title: string,
    items: T[],
    renderItem: (item: T) => JSX.Element,
    listClassName = "space-y-3",
): JSX.Element | undefined =>
    items.length > 0 ? (
        <Section title={title}>
            <div className={listClassName}>
                {items.map((item) => renderItem(item))}
            </div>
        </Section>
    ) : undefined;

const renderBlockSection = (
    title: string,
    content: JSX.Element | undefined,
): JSX.Element | undefined =>
    content ? (
        <Section title={title}>
            <div className="border-muted border-l pl-3">{content}</div>
        </Section>
    ) : undefined;

const renderRoleMessage = (message: TraceMessage): JSX.Element => (
    <div
        className="border-muted space-y-1 border-l pl-3"
        key={`${message.role}-${message.content}`}
    >
        <div className="text-muted-foreground text-xs uppercase">
            {message.role}
        </div>
        {renderMessageContent(message)}
    </div>
);

const renderToolArgumentsItem = (tool: {
    name: string;
    arguments: string;
}): JSX.Element => (
    <div
        className="border-muted space-y-1 border-l pl-3"
        key={`${tool.name}-${tool.arguments}`}
    >
        <div className="text-xs font-semibold">{tool.name}</div>
        <ContentValue value={tool.arguments} />
    </div>
);

const renderToolResultItem = (tool: {
    name: string;
    result: string;
}): JSX.Element => (
    <div
        className="border-muted space-y-1 border-l pl-3"
        key={`${tool.name}-${tool.result}`}
    >
        <div className="text-xs font-semibold">{tool.name}</div>
        <ContentValue value={tool.result} />
    </div>
);

export const SpanSection = memo(
    ({
        span,
        traceStart,
        traceEnd,
        title,
        subtitle,
        anchorId,
        isSelected,
    }: SpanSectionProps): JSX.Element => {
        const model = useMemo(
            () =>
                buildSpanDetailModel({
                    span,
                    traceStart,
                    traceEnd,
                    title,
                    subtitle,
                }),
            [span, traceEnd, traceStart, subtitle, title],
        );

        const hasSubtitle =
            model.subtitle !== undefined && model.subtitle.trim() !== "";
        const hasPrompt =
            model.prompt !== undefined && model.prompt.trim() !== "";
        const hasResponseText =
            model.responseText !== undefined &&
            model.responseText.trim() !== "";

        return (
            <section
                className={`space-y-4 rounded-lg border px-4 py-4 ${
                    isSelected
                        ? "border-primary bg-primary/15 ring-primary/30 shadow-sm ring-1"
                        : "bg-card"
                }`}
                data-span-anchor={anchorId}
            >
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                        <h3 className="text-base font-semibold break-words">
                            {model.title}
                        </h3>
                        {hasSubtitle ? (
                            <div className="text-muted-foreground text-xs break-words">
                                {model.subtitle}
                            </div>
                        ) : undefined}
                    </div>
                    <div className="text-muted-foreground text-xs tabular-nums">
                        {model.durationLabel}
                    </div>
                    {model.isError ? (
                        <Badge variant="destructive">Error</Badge>
                    ) : undefined}
                </div>

                <div className="space-y-2">
                    <div className="bg-muted relative h-1 overflow-hidden rounded">
                        <div
                            className="bg-primary absolute inset-y-0 rounded"
                            style={{
                                left: `${model.offsetPct}%`,
                                width: `${model.widthPct}%`,
                            }}
                        />
                    </div>
                    <div className="text-muted-foreground grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 text-xs">
                        <div className="font-semibold">Start</div>
                        <div>{model.timing.start}</div>
                        <div className="font-semibold">End</div>
                        <div>{model.timing.end}</div>
                        <div className="font-semibold">Offset</div>
                        <div>{model.timing.offset}</div>
                    </div>
                </div>

                {renderEntryGrid(model.metadataEntries, "md:grid-cols-3")}
                {renderEntryGrid(model.usageEntries, "md:grid-cols-4")}
                {renderListSection(
                    "App Metadata",
                    model.appEntries,
                    (entry) => (
                        <div
                            className="grid grid-cols-[180px_1fr] items-start gap-x-3 gap-y-1 text-sm"
                            key={entry.key}
                        >
                            <div className="text-xs font-semibold">
                                {entry.key}
                            </div>
                            <ContentValue value={entry.value} />
                        </div>
                    ),
                    "space-y-2",
                )}
                {renderBlockSection(
                    "System instructions",
                    model.systemInstructions !== undefined &&
                        model.systemInstructions.trim() !== "" ? (
                        <ContentValue value={model.systemInstructions} />
                    ) : undefined,
                )}
                {renderBlockSection(
                    "Prompt",
                    hasPrompt ? (
                        <ContentValue value={model.prompt} />
                    ) : undefined,
                )}
                {renderListSection(
                    "Request Messages",
                    model.requestMessages,
                    renderRoleMessage,
                )}
                {renderListSection(
                    "Requested Tools",
                    model.requestTools,
                    renderToolArgumentsItem,
                )}
                {renderListSection(
                    "Response Messages",
                    model.responseMessages,
                    renderRoleMessage,
                )}
                {renderBlockSection(
                    "Response Text",
                    hasResponseText ? (
                        <ContentValue value={model.responseText} />
                    ) : undefined,
                )}
                {renderListSection(
                    "Tool Calls",
                    model.toolCalls,
                    renderToolArgumentsItem,
                )}
                {renderListSection(
                    "Tool Results",
                    model.toolResults,
                    renderToolResultItem,
                )}
            </section>
        );
    },
);
SpanSection.displayName = "SpanSection";
