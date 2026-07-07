import { ENVIRONMENT } from "@va/shared/config";
import {
    apiPost,
    handleFetchError,
    isApiError,
} from "@va/shared/lib/api-client";
import { logger } from "@va/shared/lib/logger";

import {
    type ConsentData,
    getChatId,
    getConsentData,
    getVisitorId,
} from "./storage";

interface ConsentSubmissionPayload {
    first_name: string;
    last_name: string;
    email: string;
    phone: string;
    zip: string;
    conversation_id?: string;
    visitor_id: string;
    environment?: string;
}

export const submitConsentData = async (
    consentData: ConsentData,
    chatId?: string,
): Promise<{ success: boolean; error?: string }> => {
    try {
        const visitorId = getVisitorId();

        const payload: ConsentSubmissionPayload = {
            first_name: consentData.firstName,
            last_name: consentData.lastName,
            email: consentData.email,
            phone: consentData.phone,
            zip: consentData.zip,
            visitor_id: visitorId,
            ...(chatId !== undefined && chatId !== ""
                ? { conversation_id: chatId }
                : {}),
            ...(ENVIRONMENT === "" ? {} : { environment: ENVIRONMENT }),
        };

        await apiPost<unknown>("/consent", payload);
        return { success: true };
    } catch (error) {
        if (isApiError(error)) {
            return {
                success: false,
                error: error.detail,
            };
        }

        return {
            success: false,
            error: handleFetchError(error, "Error submitting consent"),
        };
    }
};

export const submitConsentForCurrentChat = async (): Promise<void> => {
    try {
        const consentData = getConsentData();
        if (consentData === undefined) {
            return;
        }

        const currentChatId = getChatId();
        if (currentChatId === undefined || currentChatId === "") {
            return;
        }

        const result = await submitConsentData(consentData, currentChatId);
        if (!result.success) {
            logger.error("Failed to submit consent data:", result.error);
        }
    } catch (error) {
        logger.error("Error submitting current chat consent:", error);
    }
};
