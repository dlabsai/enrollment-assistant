import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import { Input } from "@va/shared/components/ui/input";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
} from "@va/shared/components/ui/sheet";
import { Spinner } from "@va/shared/components/ui/spinner";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { cn } from "@va/shared/lib/utils";
import {
    Bot,
    ChevronLeft,
    ChevronRight,
    GitBranch,
    UserRound,
} from "lucide-react";
import { type JSX, useMemo, useState } from "react";
import {
    Button as AriaButton,
    Collection,
    type Selection,
    Tree,
    TreeItem,
    TreeItemContent,
} from "react-aria-components";

import { formatLocaleNumber } from "../../lib/number-format";
import {
    type ConversationTreeMessage,
    type ConversationTreeState,
    hasConversationBranches,
} from "../lib/conversation-tree";

interface BranchTreeItem {
    children: BranchTreeItem[];
    message: ConversationTreeMessage;
}

const buildTreeItems = (
    tree: ConversationTreeState,
    messageIds: string[],
): BranchTreeItem[] =>
    messageIds.flatMap((messageId) => {
        const message = tree.messagesById.get(messageId);
        if (message === undefined) {
            return [];
        }
        return [
            {
                message,
                children: buildTreeItems(
                    tree,
                    tree.childrenByParent.get(messageId) ?? [],
                ),
            },
        ];
    });

const filterTreeItems = (
    items: BranchTreeItem[],
    normalizedQuery: string,
): BranchTreeItem[] => {
    if (normalizedQuery === "") {
        return items;
    }

    return items.flatMap((item) => {
        const filteredChildren = filterTreeItems(
            item.children,
            normalizedQuery,
        );
        const roleLabel = item.message.role === "user" ? "user" : "assistant";
        const matches =
            roleLabel.includes(normalizedQuery) ||
            item.message.content.toLocaleLowerCase().includes(normalizedQuery);
        if (!matches && filteredChildren.length === 0) {
            return [];
        }
        return [{ ...item, children: filteredChildren }];
    });
};

const getMessagePreview = (content: string): string => {
    const compact = content.replaceAll(/\s+/gu, " ").trim();
    return compact === "" ? "Empty message" : compact;
};

const getTreeItemIds = (items: BranchTreeItem[]): string[] =>
    items.flatMap((item) => [
        item.message.id,
        ...getTreeItemIds(item.children),
    ]);

interface ConversationBranchSwitcherProps {
    currentMessageId: string;
    disabled?: boolean;
    onSelectMessage: (messageId: string) => Promise<boolean>;
    tree: ConversationTreeState | undefined;
}

export const ConversationBranchSwitcher = ({
    currentMessageId,
    disabled = false,
    onSelectMessage,
    tree,
}: ConversationBranchSwitcherProps): JSX.Element | undefined => {
    if (tree === undefined) {
        return undefined;
    }
    const currentMessage = tree.messagesById.get(currentMessageId);
    if (currentMessage === undefined) {
        return undefined;
    }

    const siblings =
        currentMessage.parentId === undefined
            ? tree.rootMessageIds
            : tree.childrenByParent.get(currentMessage.parentId);
    if (siblings === undefined || siblings.length < 2) {
        return undefined;
    }

    const currentIndex = siblings.indexOf(currentMessageId);
    if (currentIndex === -1) {
        return undefined;
    }

    const previousMessageId = siblings[currentIndex - 1];
    const nextMessageId = siblings[currentIndex + 1];
    const selectMessage = (messageId: string | undefined): void => {
        if (messageId !== undefined) {
            void onSelectMessage(messageId);
        }
    };

    return (
        <div className="text-muted-foreground flex items-center gap-0.5 text-xs">
            <Button
                aria-label="Previous branch"
                disabled={disabled || previousMessageId === undefined}
                onClick={() => {
                    selectMessage(previousMessageId);
                }}
                size="icon-sm"
                type="button"
                variant="ghost"
            >
                <ChevronLeft />
            </Button>
            <span className="min-w-10 text-center tabular-nums">
                {formatLocaleNumber(currentIndex + 1)} /{" "}
                {formatLocaleNumber(siblings.length)}
            </span>
            <Button
                aria-label="Next branch"
                disabled={disabled || nextMessageId === undefined}
                onClick={() => {
                    selectMessage(nextMessageId);
                }}
                size="icon-sm"
                type="button"
                variant="ghost"
            >
                <ChevronRight />
            </Button>
        </div>
    );
};

interface ConversationBranchNavigatorProps {
    compactTrigger?: boolean;
    disabled?: boolean;
    loading?: boolean;
    mode: "author" | "review";
    onSelectMessage: (messageId: string) => Promise<boolean>;
    tree: ConversationTreeState | undefined;
    viewedPath: string[];
}

export const ConversationBranchNavigator = ({
    compactTrigger = false,
    disabled = false,
    loading = false,
    mode,
    onSelectMessage,
    tree,
    viewedPath,
}: ConversationBranchNavigatorProps): JSX.Element | undefined => {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const treeItems = useMemo(
        () =>
            tree === undefined ? [] : buildTreeItems(tree, tree.rootMessageIds),
        [tree],
    );
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const filteredItems = useMemo(
        () => filterTreeItems(treeItems, normalizedQuery),
        [normalizedQuery, treeItems],
    );

    if (!hasConversationBranches(tree)) {
        return undefined;
    }

    const currentPath = new Set(tree.currentBranchPath);
    const viewedPathSet = new Set(viewedPath);
    const currentLeafId = tree.currentBranchPath.at(-1);
    const viewedLeafId = viewedPath.at(-1);
    const defaultExpandedKeys =
        normalizedQuery === ""
            ? [...new Set([...tree.currentBranchPath, ...viewedPath])]
            : getTreeItemIds(filteredItems);

    const selectMessage = async (messageId: string): Promise<void> => {
        if (!disabled && (await onSelectMessage(messageId))) {
            setOpen(false);
        }
    };

    const handleSelectionChange = (selection: Selection): void => {
        if (selection === "all") {
            return;
        }
        const [messageId] = [...selection];
        if (typeof messageId === "string") {
            void selectMessage(messageId);
        }
    };

    const renderItem = (item: BranchTreeItem): JSX.Element => {
        const { children, message } = item;
        const isCurrentPath = currentPath.has(message.id);
        const isViewedPath = viewedPathSet.has(message.id);
        const isCurrentLeaf = message.id === currentLeafId;
        const isViewedLeaf = message.id === viewedLeafId;
        const childCount = tree.childrenByParent.get(message.id)?.length ?? 0;
        const preview = getMessagePreview(message.content);

        return (
            <TreeItem
                className={({ isFocusVisible }) =>
                    cn(
                        "rounded-md outline-none",
                        isViewedPath && "bg-accent/60",
                        isCurrentPath &&
                            !isViewedPath &&
                            "border-primary border-l-2",
                        isFocusVisible && "ring-ring ring-2 ring-offset-1",
                    )
                }
                id={message.id}
                isDisabled={disabled}
                textValue={`${message.role} ${preview}`}
            >
                <TreeItemContent>
                    {({ hasChildItems, isExpanded, level }) => (
                        <div
                            className="flex min-w-0 items-center gap-2 px-2 py-1.5"
                            style={{
                                paddingInlineStart: `${Math.min(level - 1, 8) * 12 + 8}px`,
                            }}
                        >
                            {hasChildItems ? (
                                <AriaButton
                                    className="hover:bg-accent focus-visible:ring-ring flex size-6 shrink-0 items-center justify-center rounded-sm outline-none focus-visible:ring-2"
                                    slot="chevron"
                                >
                                    <ChevronRight
                                        className={cn(
                                            "size-3.5 transition-transform",
                                            isExpanded && "rotate-90",
                                        )}
                                    />
                                </AriaButton>
                            ) : (
                                <span className="size-6 shrink-0" />
                            )}
                            {message.role === "user" ? (
                                <UserRound className="text-muted-foreground size-4 shrink-0" />
                            ) : (
                                <Bot className="text-muted-foreground size-4 shrink-0" />
                            )}
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-1.5">
                                    <span className="text-xs font-medium">
                                        {message.role === "user"
                                            ? "User"
                                            : "Assistant"}
                                    </span>
                                    {childCount > 1 && (
                                        <Badge variant="outline">
                                            {formatLocaleNumber(childCount)}{" "}
                                            branches
                                        </Badge>
                                    )}
                                    {isCurrentLeaf && (
                                        <Badge variant="outline">Current</Badge>
                                    )}
                                    {isViewedLeaf && !isCurrentLeaf && (
                                        <Badge variant="secondary">
                                            Viewing
                                        </Badge>
                                    )}
                                </div>
                                <p className="text-muted-foreground truncate text-xs">
                                    {preview}
                                </p>
                            </div>
                        </div>
                    )}
                </TreeItemContent>
                {children.length > 0 && (
                    <Collection items={children}>{renderItem}</Collection>
                )}
            </TreeItem>
        );
    };

    const trigger = (
        <Button
            aria-label={
                compactTrigger ? "Show conversation branches" : undefined
            }
            disabled={disabled}
            size={compactTrigger ? "icon" : "sm"}
            type="button"
            variant={compactTrigger ? "ghost" : "outline"}
        >
            {compactTrigger ? (
                <GitBranch />
            ) : (
                <GitBranch data-icon="inline-start" />
            )}
            {compactTrigger ? (
                <span className="sr-only">Branches</span>
            ) : (
                "Branches"
            )}
        </Button>
    );

    return (
        <Sheet
            onOpenChange={setOpen}
            open={open}
        >
            {compactTrigger ? (
                <Tooltip>
                    <TooltipTrigger
                        render={<SheetTrigger render={trigger} />}
                    />
                    <TooltipContent side="top">Branches</TooltipContent>
                </Tooltip>
            ) : (
                <SheetTrigger render={trigger} />
            )}
            <SheetContent className="w-[min(90vw,32rem)]! max-w-none! gap-0 p-0">
                <SheetHeader className="border-b pr-12">
                    <SheetTitle>Conversation branches</SheetTitle>
                    <SheetDescription>
                        {mode === "author"
                            ? "Selecting another path makes it the current conversation branch."
                            : "Selecting another path changes only this view. The current conversation branch is not changed."}
                    </SheetDescription>
                </SheetHeader>
                <div className="border-b p-3">
                    <Input
                        aria-label="Search conversation branches"
                        onChange={(event) => {
                            setQuery(event.target.value);
                        }}
                        placeholder="Search messages..."
                        value={query}
                    />
                </div>
                <div className="min-h-0 flex-1 overflow-auto p-2">
                    {loading && (
                        <div className="text-muted-foreground flex items-center gap-2 px-2 py-1 text-xs">
                            <Spinner />
                            Switching branch...
                        </div>
                    )}
                    <Tree
                        aria-busy={loading}
                        aria-label="Conversation messages"
                        defaultExpandedKeys={defaultExpandedKeys}
                        items={filteredItems}
                        key={`${tree.rootMessageIds.join(":")}-${tree.messagesById.size}-${normalizedQuery}-${currentLeafId}-${viewedLeafId}`}
                        onSelectionChange={handleSelectionChange}
                        renderEmptyState={() => (
                            <p className="text-muted-foreground px-2 py-6 text-center text-sm">
                                No matching messages.
                            </p>
                        )}
                        selectedKeys={
                            viewedLeafId === undefined ||
                            !defaultExpandedKeys.includes(viewedLeafId)
                                ? []
                                : [viewedLeafId]
                        }
                        selectionBehavior="replace"
                        selectionMode="single"
                    >
                        {renderItem}
                    </Tree>
                </div>
            </SheetContent>
        </Sheet>
    );
};
