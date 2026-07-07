import type { JSX } from "react";

import { formatMessageTimestamp } from "../../lib/date-format";
import type { Message } from "../types";

export const renderMessageTimestampFooter = (
    message: Message | undefined,
): JSX.Element | undefined => {
    if (message === undefined || !Number.isFinite(message.createdAt)) {
        return undefined;
    }

    const createdAt = new Date(message.createdAt);

    return (
        <span
            className="inline-flex items-center gap-1 tabular-nums"
            title={createdAt.toISOString()}
        >
            {formatMessageTimestamp(createdAt)}
        </span>
    );
};
