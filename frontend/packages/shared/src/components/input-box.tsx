import { Button } from "@va/shared/components/ui/button";
import { Textarea } from "@va/shared/components/ui/textarea";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@va/shared/components/ui/tooltip";
import { cn } from "@va/shared/lib/utils";
import { ArrowUp } from "lucide-react";
import {
    type JSX,
    type KeyboardEvent,
    type ReactNode,
    useEffect,
    useRef,
    useState,
} from "react";

import { STTButton } from "./stt-button";

interface InputBoxProps {
    onSend: (message: string) => void;
    disabled: boolean;
    isLoading: boolean;
    isRecording: boolean;
    onStartRecording?: () => void;
    onStopRecording?: () => void;
    showSTTButton?: boolean;
    value?: string;
    onValueChange?: (value: string) => void;

    accessory?: ReactNode;
    actionsAccessory?: ReactNode;
    variant?: "default" | "public-widget";
}

export const InputBox = ({
    onSend,
    disabled,
    isLoading,
    isRecording,
    onStartRecording,
    onStopRecording,
    showSTTButton = true,
    value,
    onValueChange,
    accessory,
    actionsAccessory,
    variant = "default",
}: InputBoxProps): JSX.Element => {
    const [uncontrolledValue, setUncontrolledValue] = useState("");
    const isControlled = value !== undefined;
    const inputValue = isControlled ? value : uncontrolledValue;
    const setInputValue = (next: string): void => {
        if (isControlled) {
            onValueChange?.(next);
        } else {
            setUncontrolledValue(next);
        }
    };

    const textareaRef = useRef<HTMLTextAreaElement | null>(null);

    const handleSend = (): void => {
        if (inputValue.trim() && !disabled && !isLoading) {
            onSend(inputValue.trim());
            setInputValue("");
        }
    };

    const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (!disabled && !isLoading) {
                handleSend();
            }
        }
    };

    const wrapperClassName =
        "border-input dark:bg-input/30 bg-transparent rounded-[24px] border shadow-xs transition-[color,box-shadow] focus-within:border-ring focus-within:ring-ring/20 focus-within:ring-[1px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive flex flex-col gap-2 pt-2 pb-2 pl-4 pr-2";

    useEffect(() => {
        const element = textareaRef.current;
        if (!element) {
            return;
        }

        // Auto-resize like ChatGPT: grow with content up to a max, then scroll.
        // 12rem (tailwind max-h-48)
        const maxHeightPx = 192;
        element.style.height = "auto";

        const nextHeight = Math.min(element.scrollHeight, maxHeightPx);
        element.style.height = `${nextHeight}px`;
        element.style.overflowY =
            element.scrollHeight > maxHeightPx ? "auto" : "hidden";
    }, [inputValue]);

    const handleSTTClick = (): void => {
        if (isRecording) {
            onStopRecording?.();
        } else {
            onStartRecording?.();
        }
    };

    const isSendDisabled =
        disabled || isLoading || !inputValue.trim() || isRecording;

    const textareaClassName = cn(
        "max-h-48 min-h-9 flex-1 resize-none overflow-y-auto border-0 bg-transparent px-0 py-2 text-base leading-5 shadow-none outline-none focus:border-0 focus:outline-none focus:ring-0 focus-visible:border-0 focus-visible:outline-none focus-visible:ring-0 dark:bg-transparent md:text-base",
        variant === "public-widget" &&
            "!text-[length:var(--text-widget)] !border-0 !outline-none !ring-0 !shadow-none focus:!border-0 focus:!outline-none focus:!ring-0 focus:!shadow-none focus-visible:!border-0 focus-visible:!outline-none focus-visible:!ring-0 focus-visible:!shadow-none",
    );

    return (
        <div className="flex flex-col gap-2">
            <div
                className={wrapperClassName}
                data-recording={isRecording}
                data-slot="chat-composer"
            >
                <div className="flex items-end gap-1.5">
                    <Textarea
                        aria-disabled={isLoading}
                        className={textareaClassName}
                        disabled={disabled}
                        onChange={(event) => {
                            setInputValue(event.target.value);
                        }}
                        onKeyDown={handleKeyDown}
                        placeholder="Type your message..."
                        readOnly={isRecording}
                        ref={textareaRef}
                        rows={1}
                        value={inputValue}
                    />

                    <div className="flex items-center gap-1.5">
                        {showSTTButton && (
                            <Tooltip>
                                <TooltipTrigger
                                    render={
                                        <div className="border border-transparent">
                                            <STTButton
                                                disabled={disabled}
                                                isRecording={isRecording}
                                                onClick={handleSTTClick}
                                                suppressFocusRing={
                                                    variant === "public-widget"
                                                }
                                            />
                                        </div>
                                    }
                                />
                                <TooltipContent
                                    side="top"
                                    sideOffset={4}
                                >
                                    <p>{isRecording ? "Stop" : "Dictate"}</p>
                                </TooltipContent>
                            </Tooltip>
                        )}

                        {actionsAccessory}

                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <div className="flex border border-transparent">
                                        <Button
                                            aria-label="Send message"
                                            className="rounded-full"
                                            disabled={isSendDisabled}
                                            onClick={handleSend}
                                            size="icon"
                                            type="button"
                                        >
                                            <ArrowUp
                                                aria-hidden="true"
                                                className="size-4"
                                            />
                                        </Button>
                                    </div>
                                }
                            />
                            <TooltipContent
                                side="top"
                                sideOffset={4}
                            >
                                <p>{isSendDisabled ? "Disabled" : "Send"}</p>
                            </TooltipContent>
                        </Tooltip>
                    </div>
                </div>
                {accessory}
            </div>
        </div>
    );
};
