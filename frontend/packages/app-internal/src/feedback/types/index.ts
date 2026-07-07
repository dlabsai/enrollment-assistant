import type { Rating } from "../../chat/types";

export interface FeedbackListRow {
    id: string;
    messageId: string;
    conversationId: string;
    rating: Rating;
    text?: string;
    messageRole: string;
    messagePreview: string;
    conversationTitle?: string;
    conversationSummary?: string;
    isPublic: boolean;
    conversationUserName?: string;
    conversationUserEmail?: string;
    feedbackUserName: string;
    feedbackUserEmail: string;
    createdAt: string;
    updatedAt: string;
}

export interface FeedbackListPage {
    items: FeedbackListRow[];
    total: number;
}
