import { Avatar, AvatarFallback } from "@va/shared/components/ui/avatar";
import {
    Sidebar,
    SidebarContent,
    SidebarFooter,
    SidebarGroup,
    SidebarGroupContent,
    SidebarHeader,
    SidebarMenu,
    SidebarMenuButton,
    SidebarMenuItem,
    SidebarRail,
    useSidebar,
} from "@va/shared/components/ui/sidebar";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { UNIVERSITY_NAME } from "@va/shared/config";
import {
    BarChart3,
    Bot,
    CircleHelp,
    ClipboardCheck,
    ClipboardList,
    Database,
    Feather,
    FileText,
    GraduationCap,
    History,
    ListTree,
    LogOut,
    type LucideIcon,
    MessageSquareText,
    Moon,
    PanelLeftIcon,
    SearchCheck,
    Settings,
    Sun,
    ThumbsUp,
    UserRoundCheck,
} from "lucide-react";
import { type JSX, type MouseEvent, type PointerEvent, useState } from "react";

import { hasPermission } from "../../auth/lib/permissions";
import type { UserProfile } from "../../auth/types";
import { useTheme } from "../../lib/theme-context";
import type { AppView } from "../feature-flags";

interface AppSidebarProps {
    activeView: AppView;
    onViewChange: (view: AppView) => void;
    onLogout: () => Promise<void>;
    user: UserProfile;
}

// Keep low-frequency admin views out of sidebar navigation while direct route
// access still resolves through normal permission checks.
const HIDDEN_SIDEBAR_VIEWS = new Set<AppView>(["settings"]);
const HELP_URL = String(import.meta.env.VITE_HELP_URL ?? "");
const OPEN_SIDEBAR_LABEL = "Open sidebar";
const CLOSE_SIDEBAR_LABEL = "Close sidebar";

export const AppSidebar = ({
    activeView,
    onViewChange,
    onLogout,
    user,
}: AppSidebarProps): JSX.Element => {
    const [suppressOpenSidebarTooltip, setSuppressOpenSidebarTooltip] =
        useState(false);
    const { resolvedTheme, setTheme } = useTheme();
    const { isMobile, state, toggleSidebar } = useSidebar();
    const isDarkMode = resolvedTheme === "dark";
    const themeLabel = isDarkMode
        ? "Switch to light mode"
        : "Switch to dark mode";
    const initials = user.name
        .split(" ")
        .filter(Boolean)
        .map((part) => part[0].toUpperCase())
        .slice(0, 2)
        .join("");
    const fallbackInitial =
        initials ||
        user.name.charAt(0).toUpperCase() ||
        user.email.charAt(0).toUpperCase();
    const themeText = "Theme";
    const isCollapsed = state === "collapsed";
    const showDesktopTooltip = !isMobile;
    const showCollapsedTooltip = showDesktopTooltip && isCollapsed;
    const showOpenSidebarTooltip =
        showCollapsedTooltip && !suppressOpenSidebarTooltip;

    const openSidebar = (): void => {
        setSuppressOpenSidebarTooltip(false);
        toggleSidebar();
    };

    const closeSidebar = (event: MouseEvent<HTMLButtonElement>): void => {
        if (event.detail > 0) {
            setSuppressOpenSidebarTooltip(true);
        }
        toggleSidebar();
    };

    const resetOpenSidebarTooltipOnPointerLeave = (
        event: PointerEvent<HTMLButtonElement>,
    ): void => {
        const rect = event.currentTarget.getBoundingClientRect();
        const pointerIsInsideTrigger =
            event.clientX >= rect.left &&
            event.clientX <= rect.right &&
            event.clientY >= rect.top &&
            event.clientY <= rect.bottom;

        if (!pointerIsInsideTrigger) {
            setSuppressOpenSidebarTooltip(false);
        }
    };

    const navItems = [
        {
            id: "chat",
            icon: Bot,
            label: "Chat",
            allowed: true,
        },
        {
            id: "settings",
            icon: Settings,
            label: "Settings",
            allowed: hasPermission(user, "access_settings"),
        },
        {
            id: "chats",
            icon: History,
            label: "Chats",
            allowed: hasPermission(user, "access_chats"),
        },
        {
            id: "feedback",
            icon: ThumbsUp,
            label: "Feedback",
            allowed: hasPermission(user, "access_chats"),
        },
        {
            id: "messages",
            icon: MessageSquareText,
            label: "Messages",
            allowed: hasPermission(user, "access_messages"),
        },
        {
            id: "investigate",
            icon: SearchCheck,
            label: "Investigate",
            allowed: hasPermission(user, "access_investigations"),
        },
        {
            id: "investigations",
            icon: SearchCheck,
            label: "Investigations",
            allowed: hasPermission(user, "access_investigations"),
        },
        {
            id: "traces",
            icon: ListTree,
            label: "Traces",
            allowed: hasPermission(user, "access_traces"),
        },
        {
            id: "usage",
            icon: BarChart3,
            label: "Usage",
            allowed: hasPermission(user, "access_usage"),
        },
        {
            id: "analytics",
            icon: BarChart3,
            label: "Chat Analytics",
            allowed: hasPermission(user, "access_analytics"),
        },
        {
            id: "adoption",
            icon: UserRoundCheck,
            label: "Adoption",
            allowed: hasPermission(user, "access_adoption"),
        },
        {
            id: "public-analytics",
            icon: BarChart3,
            label: "Public Analytics",
            allowed: hasPermission(user, "access_public_analytics"),
        },
        {
            id: "rag-viewer",
            icon: FileText,
            label: "KB Viewer",
            allowed: hasPermission(user, "access_rag_viewer"),
        },
        {
            id: "rag-exclusions",
            icon: SearchCheck,
            label: "KB Controls",
            allowed: hasPermission(user, "access_rag_exclusions"),
        },
        {
            id: "rag",
            icon: Database,
            label: "KB Builder",
            allowed: hasPermission(user, "access_rag"),
        },
        {
            id: "rag-jobs",
            icon: History,
            label: "KB Builder Jobs",
            allowed: hasPermission(user, "access_rag"),
        },
        {
            id: "eval-cases",
            icon: ClipboardList,
            label: "Eval Cases",
            allowed: hasPermission(user, "access_evals"),
        },
        {
            id: "evals",
            icon: ClipboardCheck,
            label: "Eval Runner",
            allowed: hasPermission(user, "access_evals"),
        },
        {
            id: "eval-reports",
            icon: FileText,
            label: "Eval Reports",
            allowed: hasPermission(user, "access_evals"),
        },
        {
            id: "eval-traces",
            icon: ListTree,
            label: "Eval Traces",
            allowed: hasPermission(user, "access_evals"),
        },
        {
            id: "instructions",
            icon: Feather,
            label: "Instructions",
            allowed: hasPermission(user, "access_instructions"),
        },
        {
            id: "rbac",
            icon: Settings,
            label: "Access Controls",
            allowed: hasPermission(user, "access_rbac"),
        },
    ] satisfies {
        id: AppView;
        icon: LucideIcon;
        label: string;
        allowed: boolean;
    }[];

    return (
        <Sidebar collapsible="icon">
            <SidebarHeader>
                <div className="flex items-center justify-between gap-2 px-2 group-data-[collapsible=icon]:px-0">
                    <div className="flex items-center gap-2">
                        <div className="relative flex size-6 items-center justify-center group-data-[collapsible=icon]:size-8">
                            <Tooltip disabled={!showOpenSidebarTooltip}>
                                <TooltipTrigger
                                    delay={0}
                                    render={
                                        <button
                                            aria-hidden={!isCollapsed}
                                            className="text-foreground hover:bg-accent hover:text-accent-foreground pointer-events-none absolute inset-0 flex items-center justify-center rounded-md transition-colors group-data-[collapsible=icon]:pointer-events-auto"
                                            onClick={
                                                isCollapsed
                                                    ? openSidebar
                                                    : undefined
                                            }
                                            onPointerLeave={
                                                resetOpenSidebarTooltipOnPointerLeave
                                            }
                                            tabIndex={isCollapsed ? 0 : -1}
                                            type="button"
                                        >
                                            <GraduationCap
                                                aria-hidden="true"
                                                className="size-6 transition-opacity group-data-[collapsible=icon]:size-4 group-data-[collapsible=icon]:group-hover:opacity-0"
                                            />
                                            <PanelLeftIcon
                                                aria-hidden="true"
                                                className="absolute size-4 opacity-0 transition-opacity group-data-[collapsible=icon]:group-hover:opacity-100"
                                            />
                                            <span className="sr-only">
                                                {OPEN_SIDEBAR_LABEL}
                                            </span>
                                        </button>
                                    }
                                />
                                <TooltipContent
                                    align="center"
                                    hidden={!showOpenSidebarTooltip}
                                    side="right"
                                >
                                    {OPEN_SIDEBAR_LABEL}
                                </TooltipContent>
                            </Tooltip>
                        </div>
                        <div className="font-header text-sm leading-tight font-semibold group-data-[collapsible=icon]:hidden">
                            <div>{UNIVERSITY_NAME}</div>
                            <div className="text-xs font-normal">
                                Enrollment Assistant
                            </div>
                        </div>
                    </div>
                    {!isCollapsed && (
                        <Tooltip disabled={!showDesktopTooltip}>
                            <TooltipTrigger
                                delay={0}
                                render={
                                    <button
                                        className="text-foreground hover:bg-accent hover:text-accent-foreground flex size-7 items-center justify-center rounded-md transition-colors"
                                        onClick={closeSidebar}
                                        type="button"
                                    >
                                        <PanelLeftIcon className="size-4" />
                                        <span className="sr-only">
                                            {CLOSE_SIDEBAR_LABEL}
                                        </span>
                                    </button>
                                }
                            />
                            <TooltipContent
                                align="center"
                                hidden={!showDesktopTooltip}
                                side="right"
                            >
                                {CLOSE_SIDEBAR_LABEL}
                            </TooltipContent>
                        </Tooltip>
                    )}
                </div>
            </SidebarHeader>

            <SidebarContent>
                <SidebarGroup>
                    <SidebarGroupContent>
                        <SidebarMenu>
                            {navItems
                                .filter(
                                    (item) =>
                                        item.allowed &&
                                        !HIDDEN_SIDEBAR_VIEWS.has(item.id),
                                )
                                .map((item) => (
                                    <SidebarMenuItem key={item.id}>
                                        <SidebarMenuButton
                                            data-nav={item.id}
                                            isActive={activeView === item.id}
                                            onClick={() => {
                                                onViewChange(item.id);
                                            }}
                                            tooltip={item.label}
                                            type="button"
                                        >
                                            <item.icon />
                                            <span>{item.label}</span>
                                        </SidebarMenuButton>
                                    </SidebarMenuItem>
                                ))}
                        </SidebarMenu>
                    </SidebarGroupContent>
                </SidebarGroup>
            </SidebarContent>
            <SidebarFooter>
                <SidebarMenu>
                    <SidebarMenuItem>
                        <Tooltip disabled={!showCollapsedTooltip}>
                            <TooltipTrigger
                                delay={0}
                                render={
                                    <SidebarMenuButton
                                        className="cursor-default"
                                        size="lg"
                                        type="button"
                                    >
                                        <Avatar className="h-8 w-8 rounded-lg">
                                            <AvatarFallback className="rounded-lg text-xs font-semibold">
                                                {fallbackInitial}
                                            </AvatarFallback>
                                        </Avatar>
                                        <div className="grid flex-1 text-left text-sm leading-tight">
                                            <span className="truncate font-medium">
                                                {user.name}
                                            </span>
                                            <span className="text-muted-foreground truncate text-xs">
                                                {user.email}
                                            </span>
                                        </div>
                                    </SidebarMenuButton>
                                }
                            />
                            <TooltipContent
                                align="center"
                                hidden={!showCollapsedTooltip}
                                side="right"
                            >
                                <div className="text-sm font-semibold">
                                    {user.name}
                                </div>
                                <div className="text-muted-foreground text-xs">
                                    {user.email}
                                </div>
                            </TooltipContent>
                        </Tooltip>
                    </SidebarMenuItem>
                </SidebarMenu>
                <SidebarMenu>
                    {HELP_URL && (
                        <SidebarMenuItem>
                            <SidebarMenuButton
                                render={
                                    <a
                                        href={HELP_URL}
                                        rel="noopener noreferrer"
                                        target="_blank"
                                    />
                                }
                                tooltip="Help"
                            >
                                <CircleHelp />
                                <span>Help</span>
                            </SidebarMenuButton>
                        </SidebarMenuItem>
                    )}
                    <SidebarMenuItem>
                        <SidebarMenuButton
                            onClick={() => {
                                setTheme(isDarkMode ? "light" : "dark");
                            }}
                            tooltip={themeLabel}
                            type="button"
                        >
                            {isDarkMode ? <Moon /> : <Sun />}
                            <span>{themeText}</span>
                        </SidebarMenuButton>
                    </SidebarMenuItem>
                    <SidebarMenuItem>
                        <SidebarMenuButton
                            onClick={() => {
                                void onLogout();
                            }}
                            tooltip="Logout"
                            type="button"
                        >
                            <LogOut />
                            <span>Logout</span>
                        </SidebarMenuButton>
                    </SidebarMenuItem>
                </SidebarMenu>
            </SidebarFooter>
            <SidebarRail />
        </Sidebar>
    );
};
