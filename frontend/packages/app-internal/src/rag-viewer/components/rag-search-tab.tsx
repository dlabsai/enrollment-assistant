import type {
    ColumnDef,
    OnChangeFn,
    PaginationState,
    SortingState,
} from "@tanstack/react-table";
import { Badge } from "@va/shared/components/ui/badge";
import { Input } from "@va/shared/components/ui/input";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@va/shared/components/ui/select";
import {
    ToggleGroup,
    ToggleGroupItem,
} from "@va/shared/components/ui/toggle-group";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { HelpCircle } from "lucide-react";
import type { JSX } from "react";

import { DataTable } from "../../components/data-table";
import { isDataTablePageSize } from "../../components/data-table-constants";
import { InlineError } from "../../components/page-state";
import type {
    RagViewerSearch,
    RagViewerSourceFilter,
} from "../lib/search-state";
import {
    formatNumber,
    formatSimilarity,
    formatTimestamp,
    getSourceLabel,
    l2DistanceToApproxCosineSimilarity,
    SEARCH_MODE_HELP_ITEMS,
    SORT_OPTIONS,
    SOURCE_FILTER_OPTIONS,
} from "../lib/viewer-utils";
import type { RagDocumentSimilarityMatch, RagDocumentSummary } from "../types";

interface RagSearchTabProps {
    documents: RagDocumentSummary[];
    descending: boolean;
    documentFileExtensions: string[];
    error: string | undefined;
    fileExtension: string;
    hasLoaded: boolean;
    isFullTextMode: boolean;
    isRelevanceRankedMode: boolean;
    isSimilarityMode: boolean;
    loading: boolean;
    navigateWithSearch: (
        updater: (previous: RagViewerSearch) => Partial<RagViewerSearch>,
        options?: { replace?: boolean },
    ) => void;
    offset: number;
    pageSize: RagViewerSearch["pageSize"];
    query: string;
    queryInput: string;
    searchDebounceTimeoutRef: { current: number | undefined };
    searchMode: RagViewerSearch["searchMode"];
    selectedDocumentId: string | undefined;
    selectedSourceFilterLabel: string;
    setQueryInputState: (state: { syncedQuery: string; value: string }) => void;
    setRefreshCount: (updater: (current: number) => number) => void;
    similarityMatches: RagDocumentSimilarityMatch[];
    sortBy: RagViewerSearch["sortBy"];
    sourceFilter: RagViewerSourceFilter;
    total: number;
}

const isDocumentSortBy = (value: unknown): value is RagViewerSearch["sortBy"] =>
    typeof value === "string" &&
    SORT_OPTIONS.some((option) => option.value === value);

const buildDocumentColumns = (
    isRelevanceRankedMode: boolean,
): ColumnDef<RagDocumentSummary>[] => [
    {
        id: "title",
        accessorKey: "title",
        header: "Name",
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <span className="font-medium break-words">
                {row.original.title}
                {row.original.excluded ? (
                    <Badge
                        className="ml-2"
                        variant="secondary"
                    >
                        Excluded
                    </Badge>
                ) : null}
            </span>
        ),
    },
    {
        id: "source_type",
        accessorFn: (document) => getSourceLabel(document.source_type),
        header: "Type",
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {getSourceLabel(row.original.source_type)}
            </span>
        ),
    },
    {
        id: "token_count",
        accessorKey: "token_count",
        header: () => <div className="text-right">Tokens</div>,
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatNumber(row.original.token_count)}
            </div>
        ),
    },
    {
        id: "character_count",
        accessorKey: "character_count",
        header: () => <div className="text-right">Chars</div>,
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatNumber(row.original.character_count)}
            </div>
        ),
    },
    {
        id: "chunk_count",
        accessorKey: "chunk_count",
        header: () => <div className="text-right">Chunks</div>,
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatNumber(row.original.chunk_count)}
            </div>
        ),
    },
    {
        id: "created_at",
        accessorKey: "created_at",
        header: "Created",
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {formatTimestamp(row.original.created_at)}
            </span>
        ),
    },
    {
        id: "modified_at",
        accessorKey: "modified_at",
        header: "Modified",
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {formatTimestamp(row.original.modified_at)}
            </span>
        ),
    },
    {
        id: "source_id",
        accessorKey: "source_id",
        header: "ID",
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words tabular-nums">
                {row.original.source_id}
            </span>
        ),
    },
    {
        id: "url",
        accessorKey: "url",
        header: "URL",
        enableSorting: !isRelevanceRankedMode,
        cell: ({ row }) => (
            <a
                className="text-primary block break-all hover:underline"
                href={row.original.url}
                onClick={(event) => {
                    event.stopPropagation();
                }}
                rel="noreferrer"
                target="_blank"
            >
                {row.original.url}
            </a>
        ),
    },
];

const similarityColumns: ColumnDef<RagDocumentSimilarityMatch>[] = [
    {
        id: "document",
        header: "Name",
        enableSorting: false,
        cell: ({ row }) => (
            <span className="font-medium break-words">
                {row.original.title}
                {row.original.excluded ? (
                    <Badge
                        className="ml-2"
                        variant="secondary"
                    >
                        Excluded
                    </Badge>
                ) : null}
            </span>
        ),
    },
    {
        id: "source_type",
        accessorFn: (document) => getSourceLabel(document.source_type),
        header: "Type",
        enableSorting: false,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {getSourceLabel(row.original.source_type)}
            </span>
        ),
    },
    {
        id: "sequence_number",
        accessorKey: "sequence_number",
        header: "Chunk",
        enableSorting: false,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs tabular-nums">
                #{row.original.sequence_number}
            </span>
        ),
    },
    {
        id: "content",
        header: "Matching chunk",
        enableSorting: false,
        cell: ({ row }) => (
            <div className="text-muted-foreground line-clamp-5 text-xs break-words">
                {row.original.content}
            </div>
        ),
    },
    {
        id: "similarity",
        header: () => <div className="text-right">Similarity</div>,
        enableSorting: false,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatSimilarity(
                    l2DistanceToApproxCosineSimilarity(row.original.distance),
                )}
            </div>
        ),
    },
    {
        id: "chunk_token_count",
        header: () => <div className="text-right">Chunk tokens</div>,
        enableSorting: false,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatNumber(row.original.chunk_token_count)}
            </div>
        ),
    },
    {
        id: "source_id",
        accessorKey: "source_id",
        header: "ID",
        enableSorting: false,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words tabular-nums">
                {row.original.source_id}
            </span>
        ),
    },
];

export const RagSearchTab = ({
    documents,
    descending,
    documentFileExtensions,
    error,
    fileExtension,
    hasLoaded,
    isFullTextMode,
    isRelevanceRankedMode,
    isSimilarityMode,
    loading,
    navigateWithSearch,
    offset,
    pageSize,
    query,
    queryInput,
    searchDebounceTimeoutRef,
    searchMode,
    selectedDocumentId,
    selectedSourceFilterLabel,
    setQueryInputState,
    setRefreshCount,
    similarityMatches,
    sortBy,
    sourceFilter,
    total,
}: RagSearchTabProps): JSX.Element => {
    const pagination: PaginationState = {
        pageIndex: isSimilarityMode ? 0 : Math.floor(offset / pageSize),
        pageSize,
    };
    const sorting: SortingState = isRelevanceRankedMode
        ? []
        : [{ desc: descending, id: sortBy }];
    const pageCount = isSimilarityMode
        ? 1
        : Math.max(1, Math.ceil(total / pageSize));
    const onPaginationChange: OnChangeFn<PaginationState> = (updater) => {
        const next =
            typeof updater === "function" ? updater(pagination) : updater;
        navigateWithSearch(() => ({
            document: undefined,
            page: isSimilarityMode ? 1 : next.pageIndex + 1,
            pageSize: isDataTablePageSize(next.pageSize)
                ? next.pageSize
                : pageSize,
        }));
    };
    const onSortingChange: OnChangeFn<SortingState> = (updater) => {
        if (isRelevanceRankedMode) {
            return;
        }
        const next = typeof updater === "function" ? updater(sorting) : updater;
        const [nextSort] = next;
        navigateWithSearch(() => ({
            document: undefined,
            desc: nextSort?.desc ?? false,
            page: 1,
            sortBy: isDocumentSortBy(nextSort?.id)
                ? nextSort.id
                : "modified_at",
        }));
    };

    return (
        <>
            <div className="flex items-center gap-2">
                <ToggleGroup
                    onValueChange={(value) => {
                        const [nextMode] = value;
                        if (
                            nextMode === "exact" ||
                            nextMode === "full_text" ||
                            nextMode === "similarity"
                        ) {
                            navigateWithSearch(() => ({
                                document: undefined,
                                page: 1,
                                searchMode: nextMode,
                            }));
                        }
                    }}
                    size="sm"
                    value={[searchMode]}
                    variant="outline"
                >
                    <ToggleGroupItem value="exact">Exact text</ToggleGroupItem>
                    <ToggleGroupItem value="full_text">
                        Full text
                    </ToggleGroupItem>
                    <ToggleGroupItem value="similarity">
                        Semantic
                    </ToggleGroupItem>
                </ToggleGroup>
                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger
                            aria-label="How search modes work"
                            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex size-8 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none"
                        >
                            <HelpCircle className="size-4" />
                        </TooltipTrigger>
                        <TooltipContent
                            align="start"
                            className="max-w-sm flex-col items-start gap-2 text-left leading-relaxed"
                            side="right"
                        >
                            {SEARCH_MODE_HELP_ITEMS.map((item) => (
                                <div key={item.label}>
                                    <div className="font-medium">
                                        {item.label}
                                    </div>
                                    <div>{item.description}</div>
                                </div>
                            ))}
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>

            <div className="flex flex-wrap items-center gap-3">
                <Input
                    className="min-w-64 flex-1"
                    onChange={(event) => {
                        const nextQueryValue = event.target.value;
                        setQueryInputState({
                            syncedQuery: query,
                            value: nextQueryValue,
                        });

                        if (searchDebounceTimeoutRef.current !== undefined) {
                            window.clearTimeout(
                                searchDebounceTimeoutRef.current,
                            );
                        }

                        searchDebounceTimeoutRef.current = window.setTimeout(
                            (): void => {
                                const nextQuery = nextQueryValue.trim();
                                if (nextQuery === query) {
                                    return;
                                }

                                navigateWithSearch(
                                    () => ({
                                        document: undefined,
                                        page: 1,
                                        query:
                                            nextQuery === "" ? "" : nextQuery,
                                    }),
                                    { replace: true },
                                );
                            },
                            500,
                        );
                    }}
                    placeholder="Search..."
                    value={queryInput}
                />
                <Select
                    onValueChange={(value) => {
                        if (value === null) {
                            return;
                        }
                        const nextFileExtension = value === "all" ? "" : value;
                        navigateWithSearch(() => ({
                            document: undefined,
                            fileExtension: nextFileExtension,
                            page: 1,
                        }));
                    }}
                    value={fileExtension === "" ? "all" : fileExtension}
                >
                    <SelectTrigger className="w-[140px]">
                        <SelectValue placeholder="File extension">
                            {fileExtension === ""
                                ? "All file extensions"
                                : `.${fileExtension}`}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            <SelectItem value="all">
                                All file extensions
                            </SelectItem>
                            {documentFileExtensions.map((extension) => (
                                <SelectItem
                                    key={extension}
                                    value={extension}
                                >
                                    .{extension}
                                </SelectItem>
                            ))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
                <Select
                    onValueChange={(value) => {
                        const option = SOURCE_FILTER_OPTIONS.find(
                            (item) => item.value === value,
                        );
                        if (option !== undefined) {
                            navigateWithSearch(() => ({
                                document: undefined,
                                page: 1,
                                source: option.value,
                            }));
                        }
                    }}
                    value={sourceFilter}
                >
                    <SelectTrigger className="w-[220px]">
                        <SelectValue placeholder="Source type">
                            {selectedSourceFilterLabel}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {SOURCE_FILTER_OPTIONS.map((option) => (
                                <SelectItem
                                    key={option.value}
                                    value={option.value}
                                >
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>

            {error !== undefined && hasLoaded && (
                <InlineError
                    message={error}
                    onRetry={() => {
                        setRefreshCount((current) => current + 1);
                    }}
                />
            )}

            {isSimilarityMode ? (
                <DataTable
                    columns={similarityColumns}
                    data={similarityMatches}
                    emptyMessage={
                        query.trim() === ""
                            ? "Enter a query to search indexed chunks by vector similarity."
                            : "No chunks matched the current filters."
                    }
                    isLoading={loading}
                    isRowSelected={(match) => selectedDocumentId === match.id}
                    manualPagination
                    manualSorting
                    onPaginationChange={onPaginationChange}
                    onRowClick={(match) => {
                        navigateWithSearch(() => ({ document: match.id }));
                    }}
                    onSortingChange={onSortingChange}
                    pageCount={pageCount}
                    pagination={pagination}
                    rowCount={total}
                    sorting={sorting}
                    tableClassName="min-w-[980px]"
                    wrapCellText
                />
            ) : (
                <DataTable
                    columns={buildDocumentColumns(isRelevanceRankedMode)}
                    data={documents}
                    emptyMessage={
                        isFullTextMode && query.trim() === ""
                            ? "Enter a query to search documents with PostgreSQL full-text search."
                            : "No documents matched the current filters."
                    }
                    isLoading={loading}
                    isRowSelected={(document) =>
                        selectedDocumentId === document.id
                    }
                    manualPagination
                    manualSorting
                    onPaginationChange={onPaginationChange}
                    onRowClick={(document) => {
                        navigateWithSearch(() => ({ document: document.id }));
                    }}
                    onSortingChange={onSortingChange}
                    pageCount={pageCount}
                    pagination={pagination}
                    rowCount={total}
                    sorting={sorting}
                    tableClassName="min-w-[1120px]"
                    wrapCellText
                />
            )}
        </>
    );
};
