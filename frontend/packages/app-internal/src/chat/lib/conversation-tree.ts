import type { ConversationTreeResponse, Message } from "../types";
import type { ConversationDetailSource } from "./api.ts";

export const CONVERSATION_BRANCH_LOAD_ERROR =
    "Conversation branches could not be loaded.";

export type ReviewConversationDetailSource = Extract<
    ConversationDetailSource,
    "chats" | "messages" | "investigations"
>;

type LatestRequestResult<T> =
    | { status: "current"; value: T }
    | { status: "stale" };

export interface LatestRequestCoordinator {
    invalidate: () => void;
    run: <T>(request: () => Promise<T>) => Promise<LatestRequestResult<T>>;
}

export const createLatestRequestCoordinator = (): LatestRequestCoordinator => {
    let generation = 0;

    return {
        invalidate: (): void => {
            generation += 1;
        },
        run: async <T>(
            request: () => Promise<T>,
        ): Promise<LatestRequestResult<T>> => {
            generation += 1;
            const requestGeneration = generation;
            try {
                const value = await request();
                return requestGeneration === generation
                    ? { status: "current", value }
                    : { status: "stale" };
            } catch (error) {
                if (requestGeneration !== generation) {
                    return { status: "stale" };
                }
                throw error;
            }
        },
    };
};

export type ConversationTreeMessage = Pick<
    Message,
    "id" | "role" | "content" | "parentId"
>;

export interface ConversationTreeState {
    messagesById: Map<string, ConversationTreeMessage>;
    childrenByParent: Map<string, string[]>;
    rootMessageIds: string[];
    currentBranchPath: string[];
}

export const convertConversationTree = (
    response: ConversationTreeResponse,
): ConversationTreeState => {
    const messagesById = new Map<string, ConversationTreeMessage>();
    const childrenByParent = new Map<string, string[]>();
    const rootMessageIds: string[] = [];

    for (const message of response.messages) {
        const parentId = message.parent_id ?? undefined;
        messagesById.set(message.id, {
            id: message.id,
            role: message.role,
            content: message.content,
            parentId,
        });

        if (parentId === undefined) {
            rootMessageIds.push(message.id);
        } else {
            const childIds = childrenByParent.get(parentId) ?? [];
            childIds.push(message.id);
            childrenByParent.set(parentId, childIds);
        }
    }

    return {
        messagesById,
        childrenByParent,
        rootMessageIds,
        currentBranchPath: response.current_branch_path,
    };
};

export const hasConversationBranches = (
    tree: ConversationTreeState | undefined,
): tree is ConversationTreeState =>
    tree !== undefined &&
    (tree.rootMessageIds.length > 1 ||
        [...tree.childrenByParent.values()].some(
            (childIds) => childIds.length > 1,
        ));

export const hasMessageBranchAlternatives = (
    tree: ConversationTreeState | undefined,
    messageId: string,
): boolean => {
    const message = tree?.messagesById.get(messageId);
    if (tree === undefined || message === undefined) {
        return false;
    }
    return message.parentId === undefined
        ? tree.rootMessageIds.length > 1
        : (tree.childrenByParent.get(message.parentId)?.length ?? 0) > 1;
};
