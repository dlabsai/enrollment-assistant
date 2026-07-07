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
import type { JSX } from "react";

import { DataTable } from "../../components/data-table";
import { isDataTablePageSize } from "../../components/data-table-constants";
import { InlineError } from "../../components/page-state";
import type {
    RagViewerSearch,
    RagViewerSourceFilter,
} from "../lib/search-state";
import {
    CHUNK_SORT_OPTIONS,
    formatNumber,
    formatTimestamp,
    getSourceLabel,
    SOURCE_FILTER_OPTIONS,
} from "../lib/viewer-utils";
import type { RagChunkListItem, RagChunkSortBy } from "../types";

interface RagChunksTabProps {
    chunks: RagChunkListItem[];
    descending: boolean;
    documentFileExtensions: string[];
    error: string | undefined;
    fileExtension: string;
    loading: boolean;
    navigateWithSearch: (
        updater: (previous: RagViewerSearch) => Partial<RagViewerSearch>,
        options?: { replace?: boolean },
    ) => void;
    offset: number;
    onSelectChunk: (chunkId: string) => void;
    pageSize: RagViewerSearch["pageSize"];
    query: string;
    queryInput: string;
    searchDebounceTimeoutRef: { current: number | undefined };
    selectedChunkId: string | undefined;
    selectedSourceFilterLabel: string;
    setQueryInputState: (state: { syncedQuery: string; value: string }) => void;
    setRefreshCount: (updater: (current: number) => number) => void;
    sortBy: RagChunkSortBy;
    sourceFilter: RagViewerSourceFilter;
    total: number;
}

const isChunkSortBy = (value: unknown): value is RagChunkSortBy =>
    typeof value === "string" &&
    CHUNK_SORT_OPTIONS.some((option) => option.value === value);

const chunkColumns: ColumnDef<RagChunkListItem>[] = [
    {
        id: "chunk",
        header: "Chunk",
        enableSorting: false,
        cell: ({ row }) => (
            <div className="text-muted-foreground text-xs break-words">
                <div className="text-foreground mb-1 font-medium">
                    Chunk #{row.original.sequence_number}
                </div>
                <div className="line-clamp-6">{row.original.content}</div>
            </div>
        ),
    },
    {
        id: "title",
        header: "Name",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="font-medium break-words">
                {row.original.document.title}
                {row.original.document.excluded ? (
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
        accessorFn: (chunk) => getSourceLabel(chunk.document.source_type),
        header: "Type",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {getSourceLabel(row.original.document.source_type)}
            </span>
        ),
    },
    {
        id: "token_count",
        accessorKey: "token_count",
        header: () => <div className="text-right">Tokens</div>,
        enableSorting: true,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatNumber(row.original.token_count)}
            </div>
        ),
    },
    {
        id: "character_count",
        accessorKey: "character_count",
        header: () => <div className="text-right">Chunk chars</div>,
        enableSorting: true,
        cell: ({ row }) => (
            <div className="text-right tabular-nums">
                {formatNumber(row.original.character_count)}
            </div>
        ),
    },
    {
        id: "created_at",
        accessorKey: "created_at",
        header: "Created",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {formatTimestamp(row.original.created_at)}
            </span>
        ),
    },
    {
        id: "modified_at",
        accessorKey: "updated_at",
        header: "Updated",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words">
                {formatTimestamp(row.original.updated_at)}
            </span>
        ),
    },
    {
        id: "source_id",
        accessorFn: (chunk) => chunk.document.source_id,
        header: "ID",
        enableSorting: true,
        cell: ({ row }) => (
            <span className="text-muted-foreground text-xs break-words tabular-nums">
                {row.original.document.source_id}
            </span>
        ),
    },
];

export const RagChunksTab = ({
    chunks,
    descending,
    documentFileExtensions,
    error,
    fileExtension,
    loading,
    navigateWithSearch,
    offset,
    onSelectChunk,
    pageSize,
    query,
    queryInput,
    searchDebounceTimeoutRef,
    selectedChunkId,
    selectedSourceFilterLabel,
    setQueryInputState,
    setRefreshCount,
    sortBy,
    sourceFilter,
    total,
}: RagChunksTabProps): JSX.Element => {
    const pagination: PaginationState = {
        pageIndex: Math.floor(offset / pageSize),
        pageSize,
    };
    const sorting: SortingState = [{ desc: descending, id: sortBy }];
    const pageCount = Math.max(1, Math.ceil(total / pageSize));
    const onPaginationChange: OnChangeFn<PaginationState> = (updater) => {
        const next =
            typeof updater === "function" ? updater(pagination) : updater;
        navigateWithSearch(() => ({
            document: undefined,
            page: next.pageIndex + 1,
            pageSize: isDataTablePageSize(next.pageSize)
                ? next.pageSize
                : pageSize,
        }));
    };
    const onSortingChange: OnChangeFn<SortingState> = (updater) => {
        const next = typeof updater === "function" ? updater(sorting) : updater;
        const [nextSort] = next;
        navigateWithSearch(() => ({
            document: undefined,
            desc: nextSort?.desc ?? false,
            page: 1,
            sortBy: isChunkSortBy(nextSort?.id)
                ? nextSort.id
                : "character_count",
        }));
    };

    return (
        <>
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

            {error !== undefined && (
                <InlineError
                    message={error}
                    onRetry={() => {
                        setRefreshCount((current) => current + 1);
                    }}
                />
            )}

            <DataTable
                columns={chunkColumns}
                data={chunks}
                emptyMessage="No chunks matched the current filters."
                isLoading={loading}
                isRowSelected={(chunk) => selectedChunkId === chunk.id}
                manualPagination
                manualSorting
                onPaginationChange={onPaginationChange}
                onRowClick={(chunk) => {
                    onSelectChunk(chunk.id);
                }}
                onSortingChange={onSortingChange}
                pageCount={pageCount}
                pagination={pagination}
                rowCount={total}
                sorting={sorting}
                tableClassName="min-w-[1080px]"
                wrapCellText
            />
        </>
    );
};
