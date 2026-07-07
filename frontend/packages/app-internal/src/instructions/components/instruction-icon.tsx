import { Bot, FileText, Search, Shield } from "lucide-react";
import type { JSX } from "react";

interface InstructionIconProps {
    filename: string;
}

export const InstructionIcon = ({
    filename,
}: InstructionIconProps): JSX.Element => {
    const name = filename.toLowerCase();

    const classes = "size-4 shrink-0";

    if (name.includes("chatbot") || name.includes("demo")) {
        return <Bot className={classes} />;
    }
    if (name.includes("guardrail")) {
        return <Shield className={classes} />;
    }
    if (name.includes("search")) {
        return <Search className={classes} />;
    }
    return <FileText className={classes} />;
};
