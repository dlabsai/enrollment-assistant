import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@va/shared/components/ui/dropdown-menu";
import {
    SidebarMenuAction,
    SidebarMenuButton,
    SidebarMenuItem,
    useSidebar,
} from "@va/shared/components/ui/sidebar";
import { Spinner } from "@va/shared/components/ui/spinner";
import { MoreVertical, Pencil, RefreshCw, Trash2 } from "lucide-react";
import {
    type JSX,
    memo,
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react";

import { useTheme } from "@/lib/theme-context";

import type { Chat } from "../types";

interface ChatItemProps {
    chat: Chat;
    isActive: boolean;
    canDelete: boolean;
    showUserInfo: boolean;
    onSelect: (chatId: string) => void;
    onDelete: (chatId: string) => void;
    onRename: (chatId: string, title?: string) => void;
    onRegenerateTitle: (chatId: string) => void;
}

export const ChatItem = memo(
    ({
        chat,
        isActive,
        canDelete,
        showUserInfo,
        onSelect,
        onDelete,
        onRename,
        onRegenerateTitle,
    }: ChatItemProps): JSX.Element => {
        const { isMobile } = useSidebar();
        const { resolvedTheme } = useTheme();

        const title = chat.title ?? "New Chat";
        const [displayedTitle, setDisplayedTitle] = useState(title);
        const typingTimeoutRef = useRef<number | undefined>(undefined);
        const previousTitleRef = useRef(title);

        useEffect(() => {
            if (previousTitleRef.current === title) {
                return (): void => undefined;
            }

            previousTitleRef.current = title;

            let index = 0;
            const step = (): void => {
                index += 1;
                setDisplayedTitle(title.slice(0, index));

                if (index < title.length) {
                    typingTimeoutRef.current = window.setTimeout(step, 50);
                }
            };

            const startTyping = (): void => {
                setDisplayedTitle("");
                typingTimeoutRef.current = window.setTimeout(step, 50);
            };

            typingTimeoutRef.current = window.setTimeout(startTyping, 0);

            return (): void => {
                if (typingTimeoutRef.current !== undefined) {
                    window.clearTimeout(typingTimeoutRef.current);
                }
            };
        }, [title]);

        const handleSelect = useCallback(() => {
            onSelect(chat.id);
        }, [chat.id, onSelect]);

        const handleDelete = useCallback(() => {
            onDelete(chat.id);
        }, [chat.id, onDelete]);

        const handleRename = useCallback(() => {
            onRename(chat.id, chat.title ?? undefined);
        }, [chat.id, chat.title, onRename]);

        const handleRegenerateTitle = useCallback(() => {
            onRegenerateTitle(chat.id);
        }, [chat.id, onRegenerateTitle]);

        return (
            <SidebarMenuItem>
                <SidebarMenuButton
                    className="hover:bg-muted/50 data-[active=true]:bg-muted h-8 items-center gap-2 rounded-lg px-2"
                    isActive={isActive}
                    onClick={handleSelect}
                >
                    {chat.hasUnread && !isActive && (
                        <span className="bg-primary size-1.5 shrink-0 rounded-full" />
                    )}
                    {chat.isLoading && (
                        <Spinner className="text-muted-foreground size-3 shrink-0" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-sm">
                        {displayedTitle}
                    </span>
                    {showUserInfo &&
                        chat.userName !== undefined &&
                        chat.userName !== "" && (
                            <span className="text-muted-foreground shrink-0 text-xs">
                                {chat.userName}
                            </span>
                        )}
                </SidebarMenuButton>

                {canDelete && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <SidebarMenuAction
                                    data-theme={resolvedTheme}
                                    onClick={(event) => {
                                        event.stopPropagation();
                                    }}
                                    showOnHover
                                >
                                    <MoreVertical
                                        className="size-4"
                                        key={resolvedTheme}
                                    />
                                    <span className="sr-only">More</span>
                                </SidebarMenuAction>
                            }
                        />
                        <DropdownMenuContent
                            align={isMobile ? "end" : "start"}
                            className="w-40 rounded-lg"
                            onClick={(event) => {
                                event.stopPropagation();
                            }}
                            side={isMobile ? "bottom" : "right"}
                        >
                            <DropdownMenuItem onClick={handleRename}>
                                <Pencil className="size-3" />
                                Rename
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={handleRegenerateTitle}>
                                <RefreshCw className="size-3" />
                                Regenerate title
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                                onClick={handleDelete}
                                variant="destructive"
                            >
                                <Trash2 className="size-3" />
                                Delete
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </SidebarMenuItem>
        );
    },
);

ChatItem.displayName = "ChatItem";
