import { Button } from "@va/shared/components/ui/button";
import { Input } from "@va/shared/components/ui/input";
import { Filter, RefreshCw } from "lucide-react";
import type { JSX, ReactNode } from "react";

import type { ChatUserOption } from "../chats/types";
import type { CustomTimeRange, TimeRangeValue } from "../lib/time-range";
import { PageHeaderGroup } from "./page-header";
import { TimeRangeFilter } from "./time-range-filter";
import { UserFilterPopover } from "./user-filter-popover";

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
            <UserFilterPopover
                label={selectedUserLabel}
                loading={userLoading}
                onChange={onSelectedUserChange}
                onOpenChange={(open) => {
                    onUserPopoverOpenChange(open);
                    if (open) {
                        onUserSearchInputChange("");
                    }
                }}
                onSearchInputChange={onUserSearchInputChange}
                open={userPopoverOpen}
                options={userOptions}
                searchInput={userSearchInput}
            />
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
