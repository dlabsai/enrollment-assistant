export interface ChatListRow {
    id: string;
    title?: string;
    summary?: string;
    lastMessagePreview?: string;
    userMessageCount: number;
    assistantMessageCount: number;
    createdAt: string;
    updatedAt: string;
    isPublic: boolean;
    promptSource?: string;
    userName?: string;
    userEmail?: string;
    totalCost?: number;
    feedbackUp: number;
    feedbackDown: number;
}

export interface ChatListPage {
    items: ChatListRow[];
    total: number;
}

type ChatUserOwnerGroup = "staff" | "devs";

export interface ChatUserOption {
    name?: string;
    email: string;
    platform: "internal" | "public";
    ownerGroup?: ChatUserOwnerGroup;
}
