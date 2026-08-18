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
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@va/shared/components/ui/popover";
import { ChevronsUpDown, UserRound } from "lucide-react";
import type { JSX } from "react";

import {
    getUserOptionPrimaryLabel,
    getUserOptionSecondaryLabel,
} from "../chats/lib/user-filter-options";
import type { ChatUserOption } from "../chats/types";
import { PageHeaderGroup } from "./page-header";

interface UserFilterPopoverProps {
    label: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    searchInput: string;
    onSearchInputChange: (value: string) => void;
    options: ChatUserOption[];
    loading: boolean;
    onChange: (user?: ChatUserOption) => void;
}

export const UserFilterPopover = ({
    label,
    open,
    onOpenChange,
    searchInput,
    onSearchInputChange,
    options,
    loading,
    onChange,
}: UserFilterPopoverProps): JSX.Element => (
    <PageHeaderGroup>
        <Popover
            onOpenChange={onOpenChange}
            open={open}
        >
            <PopoverTrigger
                render={
                    <Button
                        className="w-[240px] justify-between gap-2"
                        variant="outline"
                    >
                        <span className="flex min-w-0 items-center gap-2">
                            <UserRound className="text-muted-foreground" />
                            <span className="truncate">{label}</span>
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
                        onValueChange={onSearchInputChange}
                        placeholder="Search users..."
                        value={searchInput}
                    />
                    <CommandList>
                        <CommandEmpty>
                            {loading ? "Loading users..." : "No users found"}
                        </CommandEmpty>
                        <CommandGroup>
                            {searchInput === "" && (
                                <CommandItem
                                    onSelect={() => {
                                        onChange();
                                    }}
                                >
                                    All users
                                </CommandItem>
                            )}
                            {options.map((option) => (
                                <CommandItem
                                    key={`${option.platform}-${option.email}`}
                                    onSelect={() => {
                                        onChange(option);
                                    }}
                                    value={option.email}
                                >
                                    <div className="flex min-w-0 flex-1 flex-col">
                                        <span className="truncate text-sm">
                                            {getUserOptionPrimaryLabel(option)}
                                        </span>
                                        {getUserOptionSecondaryLabel(option) !==
                                            undefined && (
                                            <span className="text-muted-foreground truncate text-xs">
                                                {getUserOptionSecondaryLabel(
                                                    option,
                                                )}
                                            </span>
                                        )}
                                    </div>
                                    <Badge
                                        variant={
                                            option.platform === "public"
                                                ? "secondary"
                                                : "outline"
                                        }
                                    >
                                        {option.platform === "public"
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
);
