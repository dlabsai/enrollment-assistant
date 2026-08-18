import {
    type Dispatch,
    type SetStateAction,
    useEffect,
    useMemo,
    useState,
} from "react";

import { useAuth } from "../../auth/contexts/auth-context";
import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { fetchChatUsers } from "../lib/api";
import {
    buildOwnerGroupFilterOptions,
    buildUserFilterParams,
} from "../lib/user-filter-options";
import type { ChatUserOption } from "../types";

interface DashboardUserFilterOptions {
    initialSelectedUser?: ChatUserOption;
    platform: "both" | "internal" | "public";
}

interface DashboardUserFilterResult {
    selectedUser: ChatUserOption | undefined;
    clear: () => void;
    handleChange: (option?: ChatUserOption) => void;
    userFilterParams: {
        userEmail?: string;
        userGroup?: "staff" | "devs";
    };
    label: string;
    searchInput: string;
    handleSearchInputChange: Dispatch<SetStateAction<string>>;
    options: ChatUserOption[];
    open: boolean;
    handleOpenChange: (open: boolean) => void;
    loading: boolean;
}

export const useDashboardUserFilter = ({
    initialSelectedUser,
    platform,
}: DashboardUserFilterOptions): DashboardUserFilterResult => {
    const api = useAuthenticatedApi();
    const { user } = useAuth();
    const [selectedUser, setSelectedUser] = useState<
        ChatUserOption | undefined
    >(initialSelectedUser);
    const [searchInput, setSearchInput] = useState("");
    const [searchQuery, setSearchQuery] = useState("");
    const [options, setOptions] = useState<ChatUserOption[]>([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const ownerGroupOptions = useMemo(
        () =>
            platform === "public" ? [] : buildOwnerGroupFilterOptions(user),
        [platform, user],
    );

    useEffect(() => {
        const timeout = setTimeout(() => {
            setSearchQuery(searchInput.trim());
        }, 300);
        return (): void => { clearTimeout(timeout); };
    }, [searchInput]);

    useEffect(() => {
        let mounted = true;
        const load = async (): Promise<void> => {
            if (!open) {
                return;
            }
            setLoading(true);
            try {
                const response = await fetchChatUsers(api, {
                    platform: platform === "both" ? undefined : platform,
                    search: searchQuery,
                    limit: 50,
                });
                if (mounted) {
                    setOptions(response);
                }
            } catch {
                if (mounted) {
                    setOptions([]);
                }
            } finally {
                if (mounted) {
                    setLoading(false);
                }
            }
        };
        void load();
        return (): void => {
            mounted = false;
        };
    }, [api, open, platform, searchQuery]);

    const handleOpenChange = (nextOpen: boolean): void => {
        setOpen(nextOpen);
        if (nextOpen) {
            setSearchInput("");
            setSearchQuery("");
        }
    };
    const handleChange = (option?: ChatUserOption): void => {
        setSelectedUser(option);
        setOpen(false);
    };
    const clear = (): void => {
        setSelectedUser(undefined);
    };

    return {
        selectedUser,
        clear,
        handleChange,
        userFilterParams: buildUserFilterParams(selectedUser),
        label: selectedUser?.name ?? selectedUser?.email ?? "All users",
        searchInput,
        handleSearchInputChange: setSearchInput,
        options: [...ownerGroupOptions, ...options],
        open,
        handleOpenChange,
        loading,
    };
};
