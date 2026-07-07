import { Badge } from "@va/shared/components/ui/badge";
import { Switch } from "@va/shared/components/ui/switch";
import { cn } from "@va/shared/lib/utils";
import { ExternalLink } from "lucide-react";
import type { JSX } from "react";

import { LoadingState } from "../../components/page-state";
import {
    formatNumber,
    formatTimestamp,
    getSourceLabel,
} from "../lib/viewer-utils";
import type { RagChunkListItem, RagDocumentChunk } from "../types";

interface RagChunkDetailProps {
    documentChunks: RagDocumentChunk[];
    isDocumentChunksLoading: boolean;
    selectedChunk: RagChunkListItem | undefined;
    setShowDocumentChunks: (show: boolean) => void;
    showDocumentChunks: boolean;
}

export const RagChunkDetail = ({
    documentChunks,
    isDocumentChunksLoading,
    selectedChunk,
    setShowDocumentChunks,
    showDocumentChunks,
}: RagChunkDetailProps): JSX.Element => (
    <section className="flex h-full min-h-0 min-w-0 flex-col gap-4 overflow-hidden">
        <header className="shrink-0 space-y-2">
            <h2 className="text-base leading-snug font-medium">
                {selectedChunk === undefined
                    ? "Chunk detail"
                    : `Chunk #${selectedChunk.sequence_number}`}
            </h2>
            <div className="text-muted-foreground text-sm">
                {selectedChunk === undefined ? (
                    "Select a chunk to inspect its full content."
                ) : (
                    <div className="flex min-w-0 flex-col gap-1">
                        <span>{selectedChunk.document.title}</span>
                        <a
                            className="text-primary inline-flex min-w-0 items-center gap-1 hover:underline"
                            href={selectedChunk.document.url}
                            rel="noreferrer"
                            target="_blank"
                        >
                            <span className="min-w-0 truncate text-left">
                                {selectedChunk.document.url}
                            </span>
                            <ExternalLink className="size-3 shrink-0" />
                        </a>
                    </div>
                )}
            </div>
            {selectedChunk !== undefined && (
                <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant="secondary">
                        {getSourceLabel(selectedChunk.document.source_type)}
                    </Badge>
                    <Badge variant="outline">
                        ID {selectedChunk.document.source_id}
                    </Badge>
                    <Badge variant="outline">
                        Tokens {formatNumber(selectedChunk.token_count)}
                    </Badge>
                    <Badge variant="outline">
                        Chars {formatNumber(selectedChunk.character_count)}
                    </Badge>
                    <Badge variant="outline">
                        Updated {formatTimestamp(selectedChunk.updated_at)}
                    </Badge>
                </div>
            )}
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-3">
            {selectedChunk === undefined ? (
                <div className="text-muted-foreground text-sm">
                    No chunk selected.
                </div>
            ) : (
                <>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                        <label className="flex items-center gap-2 text-xs">
                            <span className="text-muted-foreground">
                                Show all chunks from document
                            </span>
                            <Switch
                                checked={showDocumentChunks}
                                onCheckedChange={setShowDocumentChunks}
                            />
                        </label>
                    </div>
                    <div className="min-h-0 flex-1 overflow-auto rounded-md border p-4">
                        {showDocumentChunks ? (
                            isDocumentChunksLoading &&
                            documentChunks.length === 0 ? (
                                <LoadingState className="min-h-40 text-sm" />
                            ) : documentChunks.length === 0 ? (
                                <div className="text-muted-foreground text-sm">
                                    No document chunks available.
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {documentChunks.map((chunk) => {
                                        const isSelected =
                                            chunk.id === selectedChunk.id;

                                        return (
                                            <section
                                                className={cn(
                                                    "rounded-md border p-3",
                                                    isSelected &&
                                                        "border-primary bg-primary/5 ring-primary/20 ring-1",
                                                )}
                                                key={chunk.id}
                                            >
                                                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                                                    <span className="font-medium">
                                                        Chunk #
                                                        {chunk.sequence_number}
                                                    </span>
                                                    {isSelected && (
                                                        <Badge variant="secondary">
                                                            Selected
                                                        </Badge>
                                                    )}
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
                                                <pre className="text-foreground text-xs leading-relaxed break-words whitespace-pre-wrap">
                                                    {chunk.content}
                                                </pre>
                                            </section>
                                        );
                                    })}
                                </div>
                            )
                        ) : (
                            <pre className="text-foreground text-xs leading-relaxed break-words whitespace-pre-wrap">
                                {selectedChunk.content}
                            </pre>
                        )}
                    </div>
                </>
            )}
        </div>
    </section>
);
