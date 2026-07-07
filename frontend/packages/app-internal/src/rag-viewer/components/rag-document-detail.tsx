import { Streamdown } from "@va/shared/components/streamdown";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@va/shared/components/ui/collapsible";
import {
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
} from "@va/shared/components/ui/resizable";
import { Switch } from "@va/shared/components/ui/switch";
import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import { ChevronDown, Copy, ExternalLink } from "lucide-react";
import type { JSX } from "react";

import { InlineError, LoadingState } from "../../components/page-state";
import {
    formatNumber,
    formatTimestamp,
    getSourceLabel,
    type MarkdownViewMode,
} from "../lib/viewer-utils";
import type { RagDocumentDetailData, RagDocumentSummary } from "../types";

interface RagDocumentDetailProps {
    detailError: string | undefined;
    expandAllChunks: boolean;
    expandedChunkIds: Set<string>;
    handleAllChunksExpandedChange: (checked: boolean) => void;
    handleCopyUrl: (url: string) => void;
    loadDocumentDetail: (documentId: string, force?: boolean) => Promise<void>;
    markdownViewMode: MarkdownViewMode;
    onApproveLargeDocumentRender: () => void;
    onChunkOpenChange: (chunkId: string, open: boolean) => void;
    selectedDocumentId: string | undefined;
    selectedDetail: RagDocumentDetailData | undefined;
    selectedSummary: RagDocumentSummary | undefined;
    setMarkdownViewMode: (mode: MarkdownViewMode) => void;
    setShowChunksPane: (show: boolean) => void;
    shouldGuardSelectedDocumentRender: boolean;
    showChunksPane: boolean;
}

export const RagDocumentDetail = ({
    detailError,
    expandAllChunks,
    expandedChunkIds,
    handleAllChunksExpandedChange,
    handleCopyUrl,
    loadDocumentDetail,
    markdownViewMode,
    onApproveLargeDocumentRender,
    onChunkOpenChange,
    selectedDocumentId,
    selectedDetail,
    selectedSummary,
    setMarkdownViewMode,
    setShowChunksPane,
    shouldGuardSelectedDocumentRender,
    showChunksPane,
}: RagDocumentDetailProps): JSX.Element => (
    <section className="flex h-full min-h-0 min-w-0 flex-col gap-4 overflow-hidden">
        {selectedDocumentId === undefined ? (
            <div className="text-muted-foreground text-sm">
                No document selected.
            </div>
        ) : selectedDetail === undefined && detailError === undefined ? (
            <LoadingState className="min-h-40 text-sm" />
        ) : (
            <>
                {(selectedDetail !== undefined ||
                    selectedSummary !== undefined) && (
                    <header className="shrink-0 space-y-2">
                        <h2 className="min-w-0 truncate text-base leading-snug font-medium">
                            {selectedDetail?.title ?? selectedSummary?.title}
                        </h2>
                        <div className="text-muted-foreground min-w-0 text-sm">
                            {selectedDetail !== undefined && (
                                <div className="grid max-w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
                                    <a
                                        className="text-primary inline-flex min-w-0 flex-1 items-center gap-1 hover:underline"
                                        href={selectedDetail.url}
                                        rel="noreferrer"
                                        target="_blank"
                                    >
                                        <span className="min-w-0 flex-1 truncate text-left">
                                            {selectedDetail.url}
                                        </span>
                                        <ExternalLink className="size-3 shrink-0" />
                                    </a>
                                    <Button
                                        aria-label="Copy source URL"
                                        onClick={() => {
                                            handleCopyUrl(selectedDetail.url);
                                        }}
                                        size="icon-sm"
                                        type="button"
                                        variant="outline"
                                    >
                                        <Copy className="size-3.5" />
                                    </Button>
                                </div>
                            )}
                        </div>
                        {selectedDetail !== undefined && (
                            <div className="flex flex-wrap items-center gap-2 text-xs">
                                <Badge variant="secondary">
                                    {getSourceLabel(selectedDetail.source_type)}
                                </Badge>
                                <Badge variant="outline">
                                    ID {selectedDetail.source_id}
                                </Badge>
                                {selectedDetail.excluded ? (
                                    <Badge variant="secondary">Excluded</Badge>
                                ) : null}
                                <Badge
                                    className="max-w-full truncate"
                                    variant="outline"
                                >
                                    Key {selectedDetail.source_key}
                                </Badge>
                                <Badge variant="outline">
                                    Tokens{" "}
                                    {formatNumber(selectedDetail.token_count)}
                                </Badge>
                                <Badge variant="outline">
                                    Chars{" "}
                                    {formatNumber(
                                        selectedDetail.character_count,
                                    )}
                                </Badge>
                                <Badge variant="outline">
                                    Chunks{" "}
                                    {formatNumber(selectedDetail.chunk_count)}
                                </Badge>
                                <Badge variant="outline">
                                    Created{" "}
                                    {formatTimestamp(selectedDetail.created_at)}
                                </Badge>
                                <Badge variant="outline">
                                    Modified{" "}
                                    {formatTimestamp(
                                        selectedDetail.modified_at,
                                    )}
                                </Badge>
                            </div>
                        )}
                    </header>
                )}
                <div className="flex min-h-0 flex-1 flex-col gap-4">
                    {selectedDetail === undefined &&
                        detailError !== undefined && (
                            <InlineError
                                message={detailError}
                                onRetry={() => {
                                    if (selectedDocumentId !== undefined) {
                                        void loadDocumentDetail(
                                            selectedDocumentId,
                                            true,
                                        );
                                    }
                                }}
                            />
                        )}

                    {selectedDetail === undefined ? null : (
                        <ResizablePanelGroup
                            className="min-h-0 flex-1"
                            id="rag-viewer-right-stack"
                            orientation="vertical"
                        >
                            <ResizablePanel
                                className="min-h-0"
                                defaultSize={showChunksPane ? "55%" : "100%"}
                                id="rag-viewer-document-panel"
                                maxSize={showChunksPane ? "80%" : "100%"}
                                minSize={showChunksPane ? "25%" : "100%"}
                            >
                                <section className="flex h-full min-h-0 min-w-0 flex-col gap-2 overflow-x-hidden">
                                    <div className="flex flex-wrap items-center justify-end gap-2">
                                        <ToggleGroup
                                            onValueChange={(value) => {
                                                const [nextValue] = value;
                                                if (
                                                    nextValue === "rendered" ||
                                                    nextValue === "source"
                                                ) {
                                                    setMarkdownViewMode(
                                                        nextValue,
                                                    );
                                                }
                                            }}
                                            size="sm"
                                            value={[markdownViewMode]}
                                            variant="outline"
                                        >
                                            <ToggleGroupItem value="rendered">
                                                Formatted
                                            </ToggleGroupItem>
                                            <ToggleGroupItem value="source">
                                                Plain
                                            </ToggleGroupItem>
                                        </ToggleGroup>
                                        <label className="flex items-center gap-2 text-xs">
                                            <span className="text-muted-foreground">
                                                Chunks
                                            </span>
                                            <Switch
                                                checked={showChunksPane}
                                                onCheckedChange={
                                                    setShowChunksPane
                                                }
                                            />
                                        </label>
                                    </div>
                                    <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto rounded-md border p-4">
                                        {shouldGuardSelectedDocumentRender ? (
                                            <div className="space-y-4">
                                                <div className="bg-muted/40 rounded-md border px-4 py-3 text-sm">
                                                    <div className="font-medium">
                                                        Large document
                                                    </div>
                                                    <p className="text-muted-foreground mt-1">
                                                        This document has{" "}
                                                        {formatNumber(
                                                            selectedDetail.character_count,
                                                        )}{" "}
                                                        characters. Rendering it
                                                        as formatted Markdown
                                                        may take some time.
                                                    </p>
                                                    <div className="mt-3 flex flex-wrap gap-2">
                                                        <Button
                                                            onClick={
                                                                onApproveLargeDocumentRender
                                                            }
                                                            size="sm"
                                                            type="button"
                                                        >
                                                            Render anyway
                                                        </Button>
                                                    </div>
                                                </div>
                                                <pre className="text-foreground text-xs leading-relaxed break-words whitespace-pre-wrap">
                                                    {
                                                        selectedDetail.markdown_content
                                                    }
                                                </pre>
                                            </div>
                                        ) : markdownViewMode === "rendered" ? (
                                            <Streamdown className="max-w-none break-words">
                                                {
                                                    selectedDetail.markdown_content
                                                }
                                            </Streamdown>
                                        ) : (
                                            <pre className="text-foreground text-xs leading-relaxed break-words whitespace-pre-wrap">
                                                {
                                                    selectedDetail.markdown_content
                                                }
                                            </pre>
                                        )}
                                    </div>
                                </section>
                            </ResizablePanel>

                            {showChunksPane && (
                                <ResizableHandle
                                    className="mx-2 aria-[orientation=horizontal]:mx-0 aria-[orientation=horizontal]:my-2"
                                    withHandle
                                />
                            )}

                            {showChunksPane && (
                                <ResizablePanel
                                    className="min-h-0"
                                    id="rag-viewer-chunks-panel"
                                    minSize="20%"
                                >
                                    <section className="flex h-full min-h-0 min-w-0 flex-col gap-2 overflow-x-hidden">
                                        {selectedDetail.chunks.length > 0 && (
                                            <div className="flex flex-wrap items-center justify-end gap-2">
                                                <label className="flex items-center gap-2 text-xs">
                                                    <span className="text-muted-foreground">
                                                        Expand all
                                                    </span>
                                                    <Switch
                                                        checked={
                                                            expandAllChunks
                                                        }
                                                        onCheckedChange={
                                                            handleAllChunksExpandedChange
                                                        }
                                                    />
                                                </label>
                                            </div>
                                        )}
                                        <div className="min-h-0 min-w-0 flex-1 space-y-2 overflow-x-hidden overflow-y-auto">
                                            {selectedDetail.chunks.length ===
                                            0 ? (
                                                <div className="text-muted-foreground text-sm">
                                                    No chunks available for this
                                                    document.
                                                </div>
                                            ) : (
                                                selectedDetail.chunks.map(
                                                    (chunk) => (
                                                        <Collapsible
                                                            className="group rounded-md border"
                                                            key={chunk.id}
                                                            onOpenChange={(
                                                                open,
                                                            ) => {
                                                                onChunkOpenChange(
                                                                    chunk.id,
                                                                    open,
                                                                );
                                                            }}
                                                            open={
                                                                expandAllChunks ||
                                                                expandedChunkIds.has(
                                                                    chunk.id,
                                                                )
                                                            }
                                                        >
                                                            <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left">
                                                                <div className="flex flex-wrap items-center gap-2">
                                                                    <span className="text-sm font-medium">
                                                                        Chunk #
                                                                        {
                                                                            chunk.sequence_number
                                                                        }
                                                                    </span>
                                                                    <Badge variant="outline">
                                                                        Tokens{" "}
                                                                        {formatNumber(
                                                                            chunk.token_count,
                                                                        )}
                                                                    </Badge>
                                                                    <Badge variant="outline">
                                                                        Chars{" "}
                                                                        {formatNumber(
                                                                            chunk.character_count,
                                                                        )}
                                                                    </Badge>
                                                                </div>
                                                                <ChevronDown className="text-muted-foreground size-4 transition-transform group-data-[state=open]:rotate-180" />
                                                            </CollapsibleTrigger>
                                                            <CollapsibleContent className="border-t px-3 py-3">
                                                                {markdownViewMode ===
                                                                "rendered" ? (
                                                                    <Streamdown className="max-w-none text-sm break-words">
                                                                        {
                                                                            chunk.content
                                                                        }
                                                                    </Streamdown>
                                                                ) : (
                                                                    <pre className="text-foreground text-xs leading-relaxed break-words whitespace-pre-wrap">
                                                                        {
                                                                            chunk.content
                                                                        }
                                                                    </pre>
                                                                )}
                                                            </CollapsibleContent>
                                                        </Collapsible>
                                                    ),
                                                )
                                            )}
                                        </div>
                                    </section>
                                </ResizablePanel>
                            )}
                        </ResizablePanelGroup>
                    )}
                </div>
            </>
        )}
    </section>
);
