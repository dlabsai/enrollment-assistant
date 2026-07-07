import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "@va/shared/components/ui/command";
import { Input } from "@va/shared/components/ui/input";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@va/shared/components/ui/popover";
import { ChevronsUpDown, Filter, RefreshCw, UserRound } from "lucide-react";
import type { JSX, ReactNode } from "react";

import {
    getUserOptionPrimaryLabel,
    getUserOptionSecondaryLabel,
} from "../chats/lib/user-filter-options";
import type { ChatUserOption } from "../chats/types";
import type { CustomTimeRange, TimeRangeValue } from "../lib/time-range";
import { PageHeaderGroup } from "./page-header";
import { TimeRangeFilter } from "./time-range-filter";

interface ReviewTableToolbarProps {
    searchInput: string;
    onSearchInputChange: (value: string) => void;
    selectedUserLabel: string;
    canFilterUsers: boolean;
    userPopoverOpen: boolean;
    onUserPopoverOpenChange: (open: boolean) => void;
    userSearchInput: string;
    onUserSearchInputChange: (value: string) => void;
    userOptions: ChatUserOption[];
    userLoading: boolean;
    onSelectedUserChange: (user?: ChatUserOption) => void;
    timeRange: TimeRangeValue;
    customRange: CustomTimeRange;
    onTimeRangeChange: (value: TimeRangeValue) => void;
    onCustomRangeChange: (value: CustomTimeRange) => void;
    onClear: () => void;
    onRefresh: () => void;
    extraFilters?: ReactNode;
}

export const ReviewTableToolbar = ({
    searchInput,
    onSearchInputChange,
    selectedUserLabel,
    canFilterUsers,
    userPopoverOpen,
    onUserPopoverOpenChange,
    userSearchInput,
    onUserSearchInputChange,
    userOptions,
    userLoading,
    onSelectedUserChange,
    timeRange,
    customRange,
    onTimeRangeChange,
    onCustomRangeChange,
    onClear,
    onRefresh,
    extraFilters,
}: ReviewTableToolbarProps): JSX.Element => (
    <>
        {canFilterUsers && (
            <PageHeaderGroup>
                <Popover
                    onOpenChange={(open) => {
                        onUserPopoverOpenChange(open);
                        if (open) {
                            onUserSearchInputChange("");
                        }
                    }}
                    open={userPopoverOpen}
                >
                    <PopoverTrigger
                        render={
                            <Button
                                className="w-[240px] justify-between gap-2"
                                variant="outline"
                            >
                                <span className="flex min-w-0 items-center gap-2">
                                    <UserRound className="text-muted-foreground" />
                                    <span className="truncate">
                                        {selectedUserLabel}
                                    </span>
                                </span>
                                <ChevronsUpDown className="text-muted-foreground" />
                            </Button>
                        }
                    />
                    <PopoverContent
                        align="start"
                        className="w-[320px] p-0"
                    >
                        <Command shouldFilter={false}>
                            <CommandInput
                                onValueChange={onUserSearchInputChange}
                                placeholder="Search users..."
                                value={userSearchInput}
                            />
                            <CommandList>
                                <CommandEmpty>
                                    {userLoading
                                        ? "Loading users..."
                                        : "No users found"}
                                </CommandEmpty>
                                <CommandGroup>
                                    {userSearchInput === "" && (
                                        <CommandItem
                                            onSelect={() => {
                                                onSelectedUserChange();
                                            }}
                                        >
                                            All users
                                        </CommandItem>
                                    )}
                                    {userOptions.map((user) => (
                                        <CommandItem
                                            key={`${user.platform}-${user.email}`}
                                            onSelect={() => {
                                                onSelectedUserChange(user);
                                            }}
                                            value={user.email}
                                        >
                                            <div className="flex min-w-0 flex-1 flex-col">
                                                <span className="truncate text-sm">
                                                    {getUserOptionPrimaryLabel(
                                                        user,
                                                    )}
                                                </span>
                                                {getUserOptionSecondaryLabel(
                                                    user,
                                                ) !== undefined && (
                                                    <span className="text-muted-foreground truncate text-xs">
                                                        {getUserOptionSecondaryLabel(
                                                            user,
                                                        )}
                                                    </span>
                                                )}
                                            </div>
                                            <Badge
                                                variant={
                                                    user.platform === "public"
                                                        ? "secondary"
                                                        : "outline"
                                                }
                                            >
                                                {user.platform === "public"
                                                    ? "Public"
                                                    : "Internal"}
                                            </Badge>
                                        </CommandItem>
                                    ))}
                                </CommandGroup>
                            </CommandList>
                        </Command>
                    </PopoverContent>
                </Popover>
            </PageHeaderGroup>
        )}
        <PageHeaderGroup>
            <TimeRangeFilter
                customRange={customRange}
                onChange={onTimeRangeChange}
                onCustomRangeChange={onCustomRangeChange}
                value={timeRange}
            />
        </PageHeaderGroup>
        {extraFilters}
        <PageHeaderGroup>
            <Input
                className="w-[260px]"
                onChange={(event) => {
                    onSearchInputChange(event.target.value);
                }}
                placeholder="Search..."
                value={searchInput}
            />
            <Button
                onClick={onClear}
                variant="outline"
            >
                <Filter data-icon="inline-start" />
                Clear
            </Button>
        </PageHeaderGroup>
        <Button
            onClick={onRefresh}
            variant="outline"
        >
            <RefreshCw data-icon="inline-start" />
            Refresh
        </Button>
    </>
);
