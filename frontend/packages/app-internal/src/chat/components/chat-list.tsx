import { ConfirmDialog, ErrorDialog } from "@va/shared/components/dialog";
import { HighlightedSnippet } from "@va/shared/components/highlighted-snippet";
import { HighlightedText } from "@va/shared/components/highlighted-text";
import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "@va/shared/components/ui/command";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import { Input } from "@va/shared/components/ui/input";
import { SidebarMenu } from "@va/shared/components/ui/sidebar";
import { Spinner } from "@va/shared/components/ui/spinner";
import { cn } from "@va/shared/lib/utils";
import { MessageSquare, Search, SquarePen } from "lucide-react";
import {
    type JSX,
    type UIEvent,
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useChatActions, useChatStore } from "../contexts/chat-store-context";
import { type ChatCollectionKind, searchChats } from "../lib/api";
import { createSelectSortedChats } from "../lib/store";
import type { ChatSearchResult } from "../types";
import { ChatItem } from "./chat-item";

const selectSortedChats = createSelectSortedChats();

const INITIAL_VISIBLE_COUNT = 30;
const VISIBLE_BATCH_SIZE = 10;
const SEARCH_PAGE_SIZE = 20;
const SCROLL_THRESHOLD_PX = 32;

const formatRelativeTimestamp = (value: string, now = new Date()): string => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return "";
    }

    const diffMs = Math.max(0, now.getTime() - date.getTime());
    const minuteMs = 60_000;
    const hourMs = 3_600_000;
    const dayMs = 86_400_000;

    if (diffMs < minuteMs) {
        return "just now";
    }

    if (diffMs < hourMs) {
        const minutes = Math.floor(diffMs / minuteMs);
        return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
    }

    if (diffMs < dayMs) {
        const hours = Math.floor(diffMs / hourMs);
        return `${hours} hour${hours === 1 ? "" : "s"} ago`;
    }

    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);

    if (date.toDateString() === yesterday.toDateString()) {
        return "yesterday";
    }

    if (date.getFullYear() === now.getFullYear()) {
        return date.toLocaleDateString(undefined, {
            day: "numeric",
            month: "long",
        });
    }

    return date.toLocaleDateString(undefined, {
        month: "2-digit",
        day: "2-digit",
        year: "numeric",
    });
};

interface ChatListProps {
    className?: string;
    collectionKind?: ChatCollectionKind;
    onRequestClose?: () => void;
}

export const ChatList = ({
    className,
    collectionKind = "chat",
    onRequestClose,
}: ChatListProps): JSX.Element => {
    const chats = useChatStore(selectSortedChats);
    const chatsError = useChatStore((state) => state.chatsError);
    const chatsLoaded = useChatStore((state) => state.chatsLoaded);
    const currentChatId = useChatStore((state) => state.currentChatId);
    const {
        selectChat,
        clearCurrentChat,
        deleteChat,
        renameChatTitle,
        regenerateChatTitle,
        loadChats,
    } = useChatActions();
    const api = useAuthenticatedApi();

    const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
    const [pendingDeleteId, setPendingDeleteId] = useState<
        string | undefined
    >();
    const [renameDialogOpen, setRenameDialogOpen] = useState(false);
    const [pendingRenameId, setPendingRenameId] = useState<
        string | undefined
    >();
    const [renameValue, setRenameValue] = useState("");
    const [errorDialogOpen, setErrorDialogOpen] = useState(false);
    const [errorMessage, setErrorMessage] = useState("");
    const [searchDialogOpen, setSearchDialogOpen] = useState(false);
    const [searchInput, setSearchInput] = useState("");
    const [searchQuery, setSearchQuery] = useState("");
    const [searchResults, setSearchResults] = useState<ChatSearchResult[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [searchLoadingMore, setSearchLoadingMore] = useState(false);
    const [searchHasMore, setSearchHasMore] = useState(false);
    const [searchError, setSearchError] = useState<string | undefined>();
    const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_COUNT);
    const searchQueryRef = useRef(searchQuery);
    const isInvestigationList = collectionKind === "investigation";
    const itemLabel = isInvestigationList ? "investigation" : "chat";
    const itemLabelPlural = isInvestigationList ? "investigations" : "chats";

    const clearSearchResults = useCallback((): void => {
        setSearchResults([]);
        setSearchError(undefined);
        setSearchLoading(false);
        setSearchLoadingMore(false);
        setSearchHasMore(false);
    }, []);

    const resetSearchState = useCallback((): void => {
        setSearchInput("");
        setSearchQuery("");
        clearSearchResults();
    }, [clearSearchResults]);

    const visibleChats = chats.slice(0, visibleCount);

    const handleScroll = (event: UIEvent<HTMLDivElement>): void => {
        if (visibleCount >= chats.length) {
            return;
        }

        const target = event.currentTarget;
        const nearBottom =
            target.scrollTop + target.clientHeight >=
            target.scrollHeight - SCROLL_THRESHOLD_PX;

        if (nearBottom) {
            setVisibleCount((current) =>
                Math.min(current + VISIBLE_BATCH_SIZE, chats.length),
            );
        }
    };

    const loadMoreSearchResults = async (): Promise<void> => {
        if (isInvestigationList) {
            return;
        }
        if (searchLoading || searchLoadingMore || !searchHasMore) {
            return;
        }

        const activeQuery = searchQueryRef.current;
        if (activeQuery === "") {
            return;
        }

        setSearchLoadingMore(true);

        try {
            const results = await searchChats(api, {
                search: activeQuery,
                offset: searchResults.length,
                limit: SEARCH_PAGE_SIZE,
            });

            if (searchQueryRef.current !== activeQuery) {
                return;
            }

            setSearchResults((current) => [...current, ...results]);
            setSearchHasMore(results.length === SEARCH_PAGE_SIZE);
        } catch {
            if (searchQueryRef.current === activeQuery) {
                setSearchHasMore(false);
                toast.error(`Failed to load more ${itemLabelPlural}`);
            }
        } finally {
            if (searchQueryRef.current === activeQuery) {
                setSearchLoadingMore(false);
            }
        }
    };

    const handleSearchScroll = (event: UIEvent<HTMLDivElement>): void => {
        if (searchLoading || searchLoadingMore || !searchHasMore) {
            return;
        }

        const target = event.currentTarget;
        const nearBottom =
            target.scrollTop + target.clientHeight >=
            target.scrollHeight - SCROLL_THRESHOLD_PX;

        if (nearBottom) {
            void loadMoreSearchResults();
        }
    };

    const handleNewChat = useCallback((): void => {
        clearCurrentChat();
        onRequestClose?.();
    }, [clearCurrentChat, onRequestClose]);

    const handleSelectChat = useCallback(
        (chatId: string): void => {
            void selectChat(chatId);
            onRequestClose?.();
        },
        [onRequestClose, selectChat],
    );

    const confirmDelete = useCallback((chatId: string): void => {
        setPendingDeleteId(chatId);
        setDeleteDialogOpen(true);
    }, []);

    const openRenameDialog = useCallback(
        (chatId: string, title?: string): void => {
            setPendingRenameId(chatId);
            setRenameValue(title ?? "");
            setRenameDialogOpen(true);
        },
        [],
    );

    const handleDelete = async (): Promise<void> => {
        if (pendingDeleteId === undefined) {
            return;
        }

        try {
            await deleteChat(pendingDeleteId);
            toast.success(`${isInvestigationList ? "Investigation" : "Chat"} deleted`);
        } catch {
            setErrorMessage(`Failed to delete ${itemLabel}`);
            setErrorDialogOpen(true);
        }
    };

    const handleRename = async (): Promise<void> => {
        if (pendingRenameId === undefined) {
            return;
        }

        const nextTitle = renameValue.trim();
        if (nextTitle === "") {
            setErrorMessage("Title cannot be empty");
            setErrorDialogOpen(true);
            return;
        }

        try {
            await renameChatTitle(pendingRenameId, nextTitle);
            toast.success("Title updated");
            setRenameDialogOpen(false);
        } catch {
            setErrorMessage(`Failed to rename ${itemLabel}`);
            setErrorDialogOpen(true);
        }
    };

    const handleRegenerateTitle = useCallback(
        (chatId: string): void => {
            void (async (): Promise<void> => {
                try {
                    await regenerateChatTitle(chatId);
                    toast.success("Title regenerated");
                } catch {
                    setErrorMessage("Failed to regenerate title");
                    setErrorDialogOpen(true);
                }
            })();
        },
        [regenerateChatTitle],
    );

    const handleRetry = useCallback((): void => {
        void loadChats();
    }, [loadChats]);

    useEffect(() => {
        if (!searchDialogOpen) {
            return (): void => undefined;
        }

        const timeout = setTimeout(() => {
            setSearchQuery(searchInput.trim());
        }, 250);

        return (): void => {
            clearTimeout(timeout);
        };
    }, [searchDialogOpen, searchInput]);

    useEffect(() => {
        searchQueryRef.current = searchQuery;
    }, [searchQuery]);

    useEffect(() => {
        if (!searchDialogOpen) {
            return (): void => undefined;
        }
        if (searchQuery === "") {
            const timeout = setTimeout(() => {
                clearSearchResults();
            }, 0);

            return (): void => {
                clearTimeout(timeout);
            };
        }

        let isMounted = true;
        const activeQuery = searchQuery;

        const loadResults = async (): Promise<void> => {
            setSearchLoading(true);
            setSearchLoadingMore(false);
            setSearchHasMore(false);
            setSearchError(undefined);

            try {
                if (isInvestigationList) {
                    const normalizedQuery = activeQuery.toLowerCase();
                    const results = chats
                        .filter((chat) => {
                            const title = chat.title ?? "";
                            const preview = chat.lastMessagePreview ?? "";
                            return `${title} ${preview}`
                                .toLowerCase()
                                .includes(normalizedQuery);
                        })
                        .map((chat) => ({
                            id: chat.id,
                            title: chat.title,
                            snippet: chat.lastMessagePreview ?? chat.title ?? "",
                            updatedAt: new Date(chat.updatedAt).toISOString(),
                        }));

                    if (!isMounted || searchQueryRef.current !== activeQuery) {
                        return;
                    }

                    setSearchResults(results);
                    setSearchHasMore(false);
                    return;
                }

                const results = await searchChats(api, {
                    search: activeQuery,
                    offset: 0,
                    limit: SEARCH_PAGE_SIZE,
                });

                if (!isMounted || searchQueryRef.current !== activeQuery) {
                    return;
                }

                setSearchResults(results);
                setSearchHasMore(results.length === SEARCH_PAGE_SIZE);
            } catch (error) {
                if (!isMounted || searchQueryRef.current !== activeQuery) {
                    return;
                }

                setSearchResults([]);
                setSearchHasMore(false);
                setSearchError(
                    error instanceof Error
                        ? error.message
                        : `Failed to search ${itemLabelPlural}`,
                );
            } finally {
                if (isMounted && searchQueryRef.current === activeQuery) {
                    setSearchLoading(false);
                }
            }
        };

        void loadResults();

        return (): void => {
            isMounted = false;
        };
    }, [api, chats, clearSearchResults, isInvestigationList, itemLabelPlural, searchDialogOpen, searchQuery]);

    const highlightQuery = searchQuery.trim();

    return (
        <aside
            className={cn(
                "bg-sidebar text-sidebar-foreground flex min-h-0 w-64 shrink-0 flex-col overflow-hidden border-r",
                className,
            )}
        >
            <div className="flex shrink-0 flex-col gap-2 p-2">
                {!isInvestigationList && (
                    <Button
                        className="justify-start gap-2"
                        onClick={handleNewChat}
                        size="sm"
                        variant="ghost"
                    >
                        <SquarePen className="size-4" />
                        New {itemLabel}
                    </Button>
                )}
                <Button
                    className="justify-start gap-2"
                    onClick={() => {
                        resetSearchState();
                        setSearchDialogOpen(true);
                    }}
                    size="sm"
                    variant="ghost"
                >
                    <Search className="size-4" />
                    Search {itemLabelPlural}
                </Button>
            </div>

            <div
                className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
                onScroll={handleScroll}
            >
                {chatsError !== undefined && chatsError !== "" && (
                    <div className="p-2">
                        <Alert variant="destructive">
                            <AlertDescription>
                                <div className="flex items-center justify-between gap-2">
                                    <span>{chatsError}</span>
                                    <Button
                                        onClick={handleRetry}
                                        size="sm"
                                        variant="outline"
                                    >
                                        Retry
                                    </Button>
                                </div>
                            </AlertDescription>
                        </Alert>
                    </div>
                )}

                {chatsLoaded &&
                    chatsError === undefined &&
                    chats.length === 0 && (
                        <div className="text-muted-foreground px-4 py-3 text-center text-sm">
                            No {itemLabelPlural} yet
                        </div>
                    )}

                <SidebarMenu className="gap-0.5 px-2">
                    {visibleChats.map((chat) => (
                        <ChatItem
                            canDelete={!chat.id.startsWith("__temp_")}
                            chat={chat}
                            isActive={currentChatId === chat.id}
                            key={chat.id}
                            onDelete={confirmDelete}
                            onRegenerateTitle={handleRegenerateTitle}
                            onRename={openRenameDialog}
                            onSelect={handleSelectChat}
                            showUserInfo={false}
                        />
                    ))}
                </SidebarMenu>
            </div>

            <Dialog
                onOpenChange={(open) => {
                    setSearchDialogOpen(open);
                    if (!open) {
                        resetSearchState();
                    }
                }}
                open={searchDialogOpen}
            >
                <DialogContent
                    className="overflow-hidden p-0 sm:max-w-[560px]"
                    initialFocus={false}
                    showCloseButton={false}
                >
                    <Command
                        className="**:data-[slot=command-input]:h-12 **:data-[slot=command-input-wrapper]:h-12 **:data-[slot=command-input-wrapper]:px-4"
                        shouldFilter={false}
                    >
                        <CommandInput
                            autoFocus
                            onValueChange={(value) => {
                                setSearchInput(value);
                                if (value.trim() === "") {
                                    setSearchQuery("");
                                    clearSearchResults();
                                }
                            }}
                            placeholder={`Search ${itemLabelPlural}...`}
                            value={searchInput}
                        />
                        <CommandList
                            className="relative h-[360px] max-h-[360px]"
                            onScroll={handleSearchScroll}
                        >
                            {searchLoading && (
                                <div className="text-muted-foreground absolute inset-0 flex items-center justify-center gap-2 px-4 py-3 text-center text-sm">
                                    <Spinner className="size-4" />
                                    Searching...
                                </div>
                            )}
                            {!searchLoading && searchError !== undefined && (
                                <div className="text-destructive absolute inset-0 flex items-center justify-center px-4 py-3 text-center text-sm">
                                    {searchError}
                                </div>
                            )}
                            {!searchLoading &&
                                searchError === undefined &&
                                highlightQuery === "" && (
                                    <div className="text-muted-foreground absolute inset-0 flex items-center justify-center px-4 py-3 text-center text-sm">
                                        Type to search {itemLabelPlural}
                                    </div>
                                )}
                            {!searchLoading &&
                                searchError === undefined &&
                                highlightQuery !== "" &&
                                searchResults.length === 0 && (
                                    <CommandEmpty className="text-muted-foreground absolute inset-0 flex items-center justify-center px-4 py-3 text-center text-sm">
                                        No {itemLabelPlural} found
                                    </CommandEmpty>
                                )}
                            {!searchLoading &&
                                searchError === undefined &&
                                highlightQuery !== "" &&
                                searchResults.length > 0 && (
                                    <CommandGroup>
                                        {searchResults.map((result) => {
                                            const updatedLabel =
                                                formatRelativeTimestamp(
                                                    result.updatedAt,
                                                );

                                            return (
                                                <CommandItem
                                                    className="group relative items-start"
                                                    key={result.id}
                                                    onSelect={() => {
                                                        handleSelectChat(
                                                            result.id,
                                                        );
                                                        setSearchDialogOpen(
                                                            false,
                                                        );
                                                        resetSearchState();
                                                    }}
                                                    value={result.id}
                                                >
                                                    <MessageSquare className="text-muted-foreground mt-0.5 size-4" />
                                                    <div className="min-w-0 flex-1 space-y-1 overflow-hidden">
                                                        <div className="truncate text-sm font-medium">
                                                            <HighlightedText
                                                                query={
                                                                    highlightQuery
                                                                }
                                                                text={
                                                                    result.title ??
                                                                    `New ${itemLabel}`
                                                                }
                                                            />
                                                        </div>
                                                        <div className="text-muted-foreground truncate text-xs">
                                                            <HighlightedSnippet
                                                                query={
                                                                    highlightQuery
                                                                }
                                                                text={
                                                                    result.snippet
                                                                }
                                                            />
                                                        </div>
                                                    </div>
                                                    {updatedLabel !== "" && (
                                                        <span className="bg-popover text-muted-foreground pointer-events-none absolute top-2 right-2 hidden items-center rounded-sm px-2 py-0.5 text-xs whitespace-nowrap group-hover:inline-flex group-data-[selected=true]:inline-flex">
                                                            {updatedLabel}
                                                        </span>
                                                    )}
                                                </CommandItem>
                                            );
                                        })}
                                    </CommandGroup>
                                )}
                            {searchLoadingMore && searchResults.length > 0 && (
                                <div className="text-muted-foreground flex items-center justify-center gap-2 px-4 py-2 text-xs">
                                    <Spinner className="size-3" />
                                    Loading more...
                                </div>
                            )}
                        </CommandList>
                    </Command>
                </DialogContent>
            </Dialog>

            <Dialog
                onOpenChange={(open) => {
                    setRenameDialogOpen(open);
                    if (!open) {
                        setPendingRenameId(undefined);
                        setRenameValue("");
                    }
                }}
                open={renameDialogOpen}
            >
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Rename {itemLabel}</DialogTitle>
                    </DialogHeader>
                    <div className="grid gap-2">
                        <label
                            className="text-sm font-medium"
                            htmlFor="rename-chat-title"
                        >
                            Title
                        </label>
                        <Input
                            id="rename-chat-title"
                            onChange={(event) => {
                                setRenameValue(event.target.value);
                            }}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                    event.preventDefault();
                                    if (renameValue.trim() !== "") {
                                        void handleRename();
                                    }
                                }
                            }}
                            placeholder="Enter a title"
                            value={renameValue}
                        />
                    </div>
                    <DialogFooter>
                        <Button
                            onClick={() => {
                                setRenameDialogOpen(false);
                            }}
                            type="button"
                            variant="outline"
                        >
                            Cancel
                        </Button>
                        <Button
                            disabled={renameValue.trim() === ""}
                            onClick={() => {
                                void handleRename();
                            }}
                            type="button"
                        >
                            Save
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <ConfirmDialog
                cancelLabel="Cancel"
                confirmLabel="Delete"
                description={`Are you sure you want to delete this ${itemLabel}? This action cannot be undone.`}
                onConfirm={handleDelete}
                onOpenChange={setDeleteDialogOpen}
                open={deleteDialogOpen}
                title={`Delete ${itemLabel}`}
            />

            <ErrorDialog
                description={errorMessage}
                okLabel="OK"
                onOpenChange={setErrorDialogOpen}
                open={errorDialogOpen}
                title="Error"
            />
        </aside>
    );
};
