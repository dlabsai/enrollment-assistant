import { Streamdown } from "@va/shared/components/streamdown";
import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import { FileText } from "lucide-react";
import { type JSX, useCallback, useMemo, useRef, useState } from "react";
import { JSONTree, type ShouldExpandNodeInitially } from "react-json-tree";

import { formatLocaleNumber } from "../../lib/number-format";
import { isRecord, parseJsonRecursively } from "../lib/trace-utils";
import { jsonTreeTheme, shouldExpandJsonNode } from "../lib/trace-view-utils";
import { stringifyFieldValue, stringifyValue } from "./trace-turn-content-utils";

const normalizeJsonValue = (value: unknown): unknown => {
    const parsed = parseJsonRecursively(value);
    if (isRecord(parsed) || Array.isArray(parsed)) {
        return parsed;
    }
    return undefined;
};

const isJsonLikeString = (value: string): boolean => {
    const trimmed = value.trim();
    return trimmed.startsWith("{") || trimmed.startsWith("[");
};

const createJsonValueRenderer = (
    onPreview: (content: string) => void,
): ((
    displayValue: unknown,
    rawValue: unknown,
    ...keyPath: (string | number)[]
) => JSX.Element) => {
    const renderer = (
        displayValue: unknown,
        rawValue: unknown,
        ...keyPath: (string | number)[]
    ): JSX.Element => {
        const [key] = keyPath;
        const isContentKey = key === "content";
        if (
            isContentKey &&
            typeof rawValue === "string" &&
            rawValue.trim() !== "" &&
            !isJsonLikeString(rawValue)
        ) {
            return (
                <span className="inline-flex items-start gap-1">
                    <span className="whitespace-pre-wrap">
                        {String(displayValue)}
                    </span>
                    <button
                        className="text-muted-foreground hover:text-foreground"
                        onClick={(event) => {
                            event.stopPropagation();
                            onPreview(rawValue);
                        }}
                        type="button"
                    >
                        <FileText className="size-3" />
                    </button>
                </span>
            );
        }
        return <span>{String(displayValue)}</span>;
    };
    renderer.displayName = "JsonValueRenderer";
    return renderer;
};

const MarkdownContent = ({ content }: { content: string }): JSX.Element => (
    <Streamdown className="max-w-none break-words">{content}</Streamdown>
);

const JsonValue = ({ value }: { value: unknown }): JSX.Element => {
    const [dialogContent, setDialogContent] = useState<string | undefined>();
    const [expandMode, setExpandMode] = useState<
        "auto" | "expanded" | "collapsed"
    >("auto");
    const valueRenderer = useMemo(
        () => createJsonValueRenderer(setDialogContent),
        [setDialogContent],
    );

    const shouldExpand: ShouldExpandNodeInitially = useCallback(
        (keyPath, data, level) => {
            if (expandMode === "expanded") {
                return true;
            }
            if (expandMode === "collapsed") {
                return false;
            }
            return shouldExpandJsonNode(keyPath, data, level);
        },
        [expandMode],
    );

    const treeKey = `json-${expandMode}`;

    return (
        <div className="text-sm">
            <Dialog
                onOpenChange={(open) => {
                    if (!open) {
                        setDialogContent(undefined);
                    }
                }}
                open={dialogContent !== undefined}
            >
                <div className="flex items-center justify-end pb-2">
                    <Button
                        onClick={() => {
                            setExpandMode((current) =>
                                current === "expanded"
                                    ? "collapsed"
                                    : "expanded",
                            );
                        }}
                        size="sm"
                        type="button"
                        variant="ghost"
                    >
                        {expandMode === "expanded"
                            ? "Collapse nodes"
                            : "Expand all nodes"}
                    </Button>
                </div>
                <JSONTree
                    data={value}
                    hideRoot
                    key={treeKey}
                    shouldExpandNodeInitially={shouldExpand}
                    theme={jsonTreeTheme}
                    valueRenderer={valueRenderer}
                />
                {dialogContent === undefined ? undefined : (
                    <DialogContent className="w-[88vw] max-w-[48rem] sm:max-w-[48rem]">
                        <DialogHeader>
                            <DialogTitle>Markdown preview</DialogTitle>
                        </DialogHeader>
                        <div className="max-h-[70vh] overflow-auto">
                            <MarkdownContent content={dialogContent} />
                        </div>
                    </DialogContent>
                )}
            </Dialog>
        </div>
    );
};

const safeJsonStringify = (value: unknown): string => {
    try {
        return JSON.stringify(value);
    } catch {
        return "";
    }
};

const ExpandableJson = ({
    value,
    previewHeight = 240,
}: {
    value: unknown;
    previewHeight?: number;
}): JSX.Element => {
    const serialized = useMemo(() => safeJsonStringify(value), [value]);
    const isLong = serialized.length > 800;
    const [expanded, setExpanded] = useState(!isLong);

    return (
        <div className="space-y-2">
            <div
                className={`border-muted rounded-md border px-2 py-2 ${
                    expanded ? "" : "overflow-auto"
                }`}
                style={
                    expanded ? undefined : { maxHeight: `${previewHeight}px` }
                }
            >
                <JsonValue
                    key={serialized}
                    value={value}
                />
            </div>
            {isLong ? (
                <Button
                    onClick={() => {
                        setExpanded((current) => !current);
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                >
                    {expanded ? "Show less" : "Show more"}
                </Button>
            ) : undefined}
        </div>
    );
};

const ExpandableMarkdown = ({
    content,
    previewLength = 1400,
}: {
    content: string;
    previewLength?: number;
}): JSX.Element => {
    const isLong = content.length > previewLength;
    const [expanded, setExpanded] = useState(!isLong);
    const displayContent = expanded
        ? content
        : `${content.slice(0, previewLength)}\n\n…`;

    return (
        <div className="space-y-2">
            <MarkdownContent content={displayContent} />
            {isLong ? (
                <Button
                    onClick={() => {
                        setExpanded((value) => !value);
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                >
                    {expanded ? "Show less" : "Show more"}
                </Button>
            ) : undefined}
        </div>
    );
};

const ExpandablePlainText = ({
    content,
    previewLength = 1400,
}: {
    content: string;
    previewLength?: number;
}): JSX.Element => {
    const isLong = content.length > previewLength;
    const [expanded, setExpanded] = useState(!isLong);
    const displayContent = expanded
        ? content
        : `${content.slice(0, previewLength)}\n\n…`;

    return (
        <div className="space-y-2">
            <div className="font-mono text-xs break-words whitespace-pre-wrap">
                {displayContent}
            </div>
            {isLong ? (
                <Button
                    onClick={() => {
                        setExpanded((value) => !value);
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                >
                    {expanded ? "Show less" : "Show more"}
                </Button>
            ) : undefined}
        </div>
    );
};

interface DocumentToolResult {
    type: string;
    id: number;
    title: string;
    url?: string;
    sequence_number?: number;
    updated_at?: string | null;
    content?: string;
}

const isDocumentToolResult = (value: unknown): value is DocumentToolResult =>
    isRecord(value) &&
    typeof value.type === "string" &&
    typeof value.id === "number" &&
    typeof value.title === "string";

const DOCUMENT_RESULT_PREVIEW_LENGTH = 1400;

type FindDocumentChunksV2SourceTuple = [number, number[], string];

interface FindDocumentChunksV2Result {
    content: string;
    sources: Record<string, FindDocumentChunksV2SourceTuple[]>;
}

interface ChunkSourceDisplay {
    type: string;
    id: number;
    sequenceNumbers: number[];
    title: string;
}

const isSourceTuple = (
    value: unknown,
): value is FindDocumentChunksV2SourceTuple =>
    Array.isArray(value) &&
    value.length === 3 &&
    typeof value[0] === "number" &&
    Array.isArray(value[1]) &&
    value[1].every((entry) => typeof entry === "number") &&
    typeof value[2] === "string";

const isSourcesRecord = (
    value: unknown,
): value is Record<string, FindDocumentChunksV2SourceTuple[]> =>
    isRecord(value) &&
    Object.values(value).every(
        (rows) => Array.isArray(rows) && rows.every((row) => isSourceTuple(row)),
    );

const isFindDocumentChunksV2Result = (
    value: unknown,
): value is FindDocumentChunksV2Result =>
    isRecord(value) &&
    typeof value.content === "string" &&
    isSourcesRecord(value.sources);

const isFindDocumentChunksV2ResultArray = (
    value: unknown,
): value is FindDocumentChunksV2Result[] =>
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((entry) => isFindDocumentChunksV2Result(entry));

const flattenChunkSources = (
    sources: Record<string, FindDocumentChunksV2SourceTuple[]>,
): ChunkSourceDisplay[] =>
    Object.entries(sources).flatMap(([type, rows]) =>
        rows.map(([id, sequenceNumbers, title]) => ({
            type,
            id,
            sequenceNumbers,
            title,
        })),
    );

const formatSequenceNumbers = (sequenceNumbers: number[]): string => {
    if (sequenceNumbers.length === 0) {
        return "seq -";
    }
    const label = sequenceNumbers.length === 1 ? "seq" : "seqs";
    return `${label} ${sequenceNumbers.map((entry) => formatLocaleNumber(entry)).join(", ")}`;
};

const getFindDocumentChunksV2ResultKey = (
    item: FindDocumentChunksV2Result,
    index: number,
): string => `${index}-${item.content.slice(0, 48)}`;

const FindDocumentChunksV2Card = ({
    active,
    expanded,
    formatted,
    index,
    item,
    onExpandedChange,
    total,
}: {
    active: boolean;
    expanded: boolean;
    formatted: boolean;
    index: number;
    item: FindDocumentChunksV2Result;
    onExpandedChange: (expanded: boolean) => void;
    total: number;
}): JSX.Element => {
    const sources = flattenChunkSources(item.sources);
    const isLong = item.content.length > DOCUMENT_RESULT_PREVIEW_LENGTH;
    const displayContent =
        expanded || !isLong
            ? item.content
            : `${item.content.slice(0, DOCUMENT_RESULT_PREVIEW_LENGTH)}\n\n…`;
    return (
        <article
            className={`space-y-3 rounded-md border p-3 ${
                active ? "border-primary ring-primary/30 ring-2" : ""
            }`}
        >
            <div className="text-muted-foreground text-right text-xs font-medium">
                Item {index + 1} of {total}
            </div>
            <div className="space-y-1 text-xs">
                {sources.map((source) => (
                    <div
                        className="bg-muted/30 rounded-md border px-2 py-1"
                        key={`${source.type}-${source.id}-${source.sequenceNumbers.join("-")}`}
                    >
                        <span className="font-semibold">{source.type}</span>
                        <span className="text-muted-foreground">
                            {" "}
                            #{String(source.id)} · {formatSequenceNumbers(source.sequenceNumbers)} · {source.title}
                        </span>
                    </div>
                ))}
            </div>
            <div className="border-muted space-y-3 border-t pt-3 text-sm">
                {formatted ? (
                    <MarkdownContent content={displayContent} />
                ) : (
                    <div className="font-mono text-xs break-words whitespace-pre-wrap">
                        {displayContent}
                    </div>
                )}
                {isLong ? (
                    <Button
                        onClick={() => {
                            onExpandedChange(!expanded);
                        }}
                        size="sm"
                        type="button"
                        variant="outline"
                    >
                        {expanded ? "Show beginning" : "Show full chunk"}
                    </Button>
                ) : undefined}
            </div>
        </article>
    );
};

const FindDocumentChunksV2Value = ({
    formatted,
    results,
}: {
    formatted: boolean;
    results: FindDocumentChunksV2Result[];
}): JSX.Element => {
    const [activeIndex, setActiveIndex] = useState(0);
    const [expandedByKey, setExpandedByKey] = useState<Record<string, boolean>>({});
    const itemRef = useRef<(HTMLDivElement | null)[]>([]);
    const itemKeys = useMemo(
        () => results.map((item, index) => getFindDocumentChunksV2ResultKey(item, index)),
        [results],
    );
    const safeActiveIndex = Math.min(activeIndex, Math.max(results.length - 1, 0));
    const hasMultipleItems = results.length > 1;

    const scrollToIndex = (index: number): void => {
        const nextIndex = Math.min(Math.max(index, 0), results.length - 1);
        setActiveIndex(nextIndex);
        itemRef.current[nextIndex]?.scrollIntoView({
            behavior: "smooth",
            block: "start",
        });
    };

    const setAllExpanded = (expanded: boolean): void => {
        setExpandedByKey(Object.fromEntries(itemKeys.map((key) => [key, expanded])));
    };

    return (
        <div className="space-y-3">
            <div className="bg-background/95 sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b py-2 backdrop-blur">
                <div className="text-muted-foreground text-xs font-medium">
                    Item {formatLocaleNumber(safeActiveIndex + 1)} of {formatLocaleNumber(results.length)}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    {hasMultipleItems ? (
                        <>
                            <Button
                                disabled={safeActiveIndex === 0}
                                onClick={() => {
                                    scrollToIndex(0);
                                }}
                                size="sm"
                                type="button"
                                variant="outline"
                            >
                                First
                            </Button>
                            <Button
                                disabled={safeActiveIndex === 0}
                                onClick={() => {
                                    scrollToIndex(safeActiveIndex - 1);
                                }}
                                size="sm"
                                type="button"
                                variant="outline"
                            >
                                Prev
                            </Button>
                            <Button
                                disabled={safeActiveIndex >= results.length - 1}
                                onClick={() => {
                                    scrollToIndex(safeActiveIndex + 1);
                                }}
                                size="sm"
                                type="button"
                                variant="outline"
                            >
                                Next
                            </Button>
                            <Button
                                disabled={safeActiveIndex >= results.length - 1}
                                onClick={() => {
                                    scrollToIndex(results.length - 1);
                                }}
                                size="sm"
                                type="button"
                                variant="outline"
                            >
                                Last
                            </Button>
                        </>
                    ) : undefined}
                    <Button
                        onClick={() => {
                            setAllExpanded(true);
                        }}
                        size="sm"
                        type="button"
                        variant="ghost"
                    >
                        Expand all
                    </Button>
                    <Button
                        onClick={() => {
                            setAllExpanded(false);
                        }}
                        size="sm"
                        type="button"
                        variant="ghost"
                    >
                        Collapse all
                    </Button>
                </div>
            </div>
            <div className="space-y-3">
                {results.map((item, index) => {
                    const key =
                        itemKeys[index] ?? getFindDocumentChunksV2ResultKey(item, index);
                    return (
                        <div
                            className="scroll-mt-20"
                            key={key}
                            ref={(node) => {
                                itemRef.current[index] = node;
                            }}
                        >
                            <FindDocumentChunksV2Card
                                active={index === safeActiveIndex}
                                expanded={expandedByKey[key] ?? false}
                                formatted={formatted}
                                index={index}
                                item={item}
                                onExpandedChange={(expanded) => {
                                    setExpandedByKey((current) => ({
                                        ...current,
                                        [key]: expanded,
                                    }));
                                }}
                                total={results.length}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

const DocumentResultCard = ({
    active,
    expanded,
    formatted,
    index,
    item,
    onExpandedChange,
    total,
}: {
    active: boolean;
    expanded: boolean;
    formatted: boolean;
    index: number;
    item: DocumentToolResult;
    onExpandedChange: (expanded: boolean) => void;
    total: number;
}): JSX.Element => {
    const { content, title } = item;
    const isLong =
        content !== undefined && content.length > DOCUMENT_RESULT_PREVIEW_LENGTH;
    const displayContent =
        content === undefined || expanded || !isLong
            ? content
            : `${content.slice(0, DOCUMENT_RESULT_PREVIEW_LENGTH)}\n\n…`;
    const metadata = Object.entries(item).filter(
        ([key, value]) => key !== "content" && value !== undefined && value !== null,
    );

    return (
        <article
            className={`space-y-3 rounded-md border p-3 ${
                active ? "border-primary ring-primary/30 ring-2" : ""
            }`}
        >
            <div className="space-y-2">
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="font-semibold break-words">{title}</div>
                    <div className="text-muted-foreground shrink-0 text-xs font-medium">
                        Item {index + 1} of {total}
                    </div>
                </div>
                <div className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 text-xs">
                    {metadata.map(([key, value]) => (
                        <div
                            className="contents"
                            key={key}
                        >
                            <div className="font-semibold break-words">{key}</div>
                            <div className="text-muted-foreground break-words whitespace-pre-wrap">
                                {stringifyFieldValue(key, value)}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
            {displayContent === undefined || displayContent.trim() === "" ? undefined : (
                <div className="border-muted space-y-3 border-t pt-3 text-sm">
                    {formatted ? (
                        <MarkdownContent content={displayContent} />
                    ) : (
                        <div className="font-mono text-xs break-words whitespace-pre-wrap">
                            {displayContent}
                        </div>
                    )}
                    {isLong ? (
                        <Button
                            onClick={() => {
                                onExpandedChange(!expanded);
                            }}
                            size="sm"
                            type="button"
                            variant="outline"
                        >
                            {expanded ? "Show beginning" : "Show full item"}
                        </Button>
                    ) : undefined}
                </div>
            )}
        </article>
    );
};

const getDocumentResultKey = (item: DocumentToolResult): string =>
    `${item.type}-${item.id}-${item.sequence_number ?? "document"}-${item.title}`;

const DocumentResultsValue = ({
    formatted,
    value,
}: {
    formatted: boolean;
    value: DocumentToolResult[];
}): JSX.Element => {
    const [activeIndex, setActiveIndex] = useState(0);
    const [expandedByKey, setExpandedByKey] = useState<Record<string, boolean>>({});
    const itemRef = useRef<(HTMLDivElement | null)[]>([]);
    const itemKeys = useMemo(
        () => value.map((item) => getDocumentResultKey(item)),
        [value],
    );
    const safeActiveIndex = Math.min(activeIndex, Math.max(value.length - 1, 0));
    const hasMultipleItems = value.length > 1;

    const scrollToIndex = (index: number): void => {
        const nextIndex = Math.min(Math.max(index, 0), value.length - 1);
        setActiveIndex(nextIndex);
        itemRef.current[nextIndex]?.scrollIntoView({
            behavior: "smooth",
            block: "start",
        });
    };

    const setAllExpanded = (expanded: boolean): void => {
        setExpandedByKey(
            Object.fromEntries(itemKeys.map((key) => [key, expanded])),
        );
    };

    if (value.length === 0) {
        return <div className="text-muted-foreground text-xs">No results.</div>;
    }

    return (
        <div className="space-y-3">
            <div className="bg-background/95 sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b py-2 backdrop-blur">
                <div className="text-muted-foreground text-xs font-medium">
                    Item {formatLocaleNumber(safeActiveIndex + 1)} of {formatLocaleNumber(value.length)}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    {hasMultipleItems ? (
                        <>
                            <Button
                                disabled={safeActiveIndex === 0}
                                onClick={() => {
                                    scrollToIndex(0);
                                }}
                                size="sm"
                                type="button"
                                variant="outline"
                            >
                                First
                            </Button>
                            <Button
                                disabled={safeActiveIndex === 0}
                                onClick={() => {
                                    scrollToIndex(safeActiveIndex - 1);
                                }}
                                size="sm"
                                type="button"
                                variant="outline"
                            >
                                Prev
                            </Button>
                            <Button
                                disabled={safeActiveIndex >= value.length - 1}
                                onClick={() => {
                                    scrollToIndex(safeActiveIndex + 1);
                                }}
                                size="sm"
                                type="button"
                                variant="outline"
                            >
                                Next
                            </Button>
                            <Button
                                disabled={safeActiveIndex >= value.length - 1}
                                onClick={() => {
                                    scrollToIndex(value.length - 1);
                                }}
                                size="sm"
                                type="button"
                                variant="outline"
                            >
                                Last
                            </Button>
                        </>
                    ) : undefined}
                    <Button
                        onClick={() => {
                            setAllExpanded(true);
                        }}
                        size="sm"
                        type="button"
                        variant="ghost"
                    >
                        Expand all
                    </Button>
                    <Button
                        onClick={() => {
                            setAllExpanded(false);
                        }}
                        size="sm"
                        type="button"
                        variant="ghost"
                    >
                        Collapse all
                    </Button>
                </div>
            </div>
            <div className="space-y-3">
                {value.map((item, index) => {
                    const key = itemKeys[index] ?? getDocumentResultKey(item);
                    return (
                        <div
                            className="scroll-mt-20"
                            key={key}
                            ref={(node) => {
                                itemRef.current[index] = node;
                            }}
                        >
                            <DocumentResultCard
                                active={index === safeActiveIndex}
                                expanded={expandedByKey[key] ?? false}
                                formatted={formatted}
                                index={index}
                                item={item}
                                onExpandedChange={(expanded) => {
                                    setExpandedByKey((current) => ({
                                        ...current,
                                        [key]: expanded,
                                    }));
                                }}
                                total={value.length}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export const ContentValue = ({
    formatted = true,
    value,
}: {
    formatted?: boolean;
    value: unknown;
}): JSX.Element => {
    const jsonValue = normalizeJsonValue(value);
    if (isFindDocumentChunksV2ResultArray(jsonValue)) {
        return (
            <FindDocumentChunksV2Value
                formatted={formatted}
                results={jsonValue}
            />
        );
    }
    if (
        Array.isArray(jsonValue) &&
        jsonValue.length > 0 &&
        jsonValue.every((item) => isDocumentToolResult(item))
    ) {
        return (
            <DocumentResultsValue
                formatted={formatted}
                value={jsonValue}
            />
        );
    }
    if (jsonValue !== undefined) {
        return <ExpandableJson value={jsonValue} />;
    }
    if (typeof value === "string" && isJsonLikeString(value)) {
        return <ExpandablePlainText content={value} />;
    }
    return <ExpandableMarkdown content={stringifyValue(value)} />;
};
