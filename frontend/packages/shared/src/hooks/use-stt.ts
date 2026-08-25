import { logger } from "@va/shared/lib/logger";
import { useCallback, useEffect, useRef, useState } from "react";

interface UseSTTOptions {
    enabled: boolean;
    lang: string;
    continuous: boolean;

    /**
     * Called whenever the SpeechRecognition API produces finalized transcript chunks.
     * This is invoked from the underlying event callback (not a React effect).
     */
    onFinalTranscript?: (chunk: string) => void;
    onError?: (error: SpeechRecognitionErrorEvent["error"]) => void;
}

const microphoneErrorCode = (
    error: unknown,
): SpeechRecognitionErrorEvent["error"] =>
    error instanceof DOMException &&
    (error.name === "NotAllowedError" || error.name === "SecurityError")
        ? "not-allowed"
        : "audio-capture";

export const useSTT = ({
    enabled,
    lang,
    continuous,
    onFinalTranscript,
    onError,
}: UseSTTOptions): {
    start: () => void;
    stop: () => void;
    isRecording: boolean;
    transcript: string;
    clearTranscript: () => void;
    supported: boolean;
} => {
    const [isRecording, setIsRecording] = useState(false);
    const [transcript, setTranscript] = useState("");

    const SpeechRecognition =
        (window.SpeechRecognition as
            | typeof window.SpeechRecognition
            | undefined) ??
        (window.webkitSpeechRecognition as
            | typeof window.webkitSpeechRecognition
            | undefined);
    const supported = SpeechRecognition !== undefined;

    const recognitionRef = useRef<SpeechRecognition | undefined>(undefined);
    const microphonePermissionGrantedRef = useRef(false);
    const startInProgressRef = useRef(false);
    const onFinalTranscriptRef = useRef<
        UseSTTOptions["onFinalTranscript"] | undefined
    >(undefined);
    const onErrorRef = useRef<UseSTTOptions["onError"] | undefined>(undefined);

    useEffect(() => {
        onFinalTranscriptRef.current = onFinalTranscript;
        onErrorRef.current = onError;
    }, [onFinalTranscript, onError]);

    useEffect(() => {
        if (!enabled || !supported) {
            return (): void => {
                recognitionRef.current?.stop();
                recognitionRef.current = undefined;
            };
        }

        const recognition = new SpeechRecognition();

        recognition.continuous = continuous;
        recognition.interimResults = true;
        recognition.lang = lang;

        // Immediate UI toggle: flip to "recording" when recognition starts.
        const onStart = (): void => {
            setIsRecording(true);
        };

        const onEnd = (): void => {
            setIsRecording(false);
        };

        const handleError = (event: SpeechRecognitionErrorEvent): void => {
            logger.error("Speech recognition error:", event.error);
            if (
                event.error === "not-allowed" ||
                event.error === "audio-capture"
            ) {
                microphonePermissionGrantedRef.current = false;
            }
            onErrorRef.current?.(event.error);
            setIsRecording(false);
        };

        const onResult = (event: SpeechRecognitionEvent): void => {
            let finalTranscript = "";

            // If continuous: event.results can include previous results.
            // Start at resultIndex for proper concatenation.
            for (
                let index = event.resultIndex;
                index < event.results.length;
                index += 1
            ) {
                const result = event.results.item(index);
                if (result.isFinal) {
                    finalTranscript += result[0].transcript;
                }
            }

            const finalized = finalTranscript.trim();
            if (finalized === "") {
                return;
            }

            const callback = onFinalTranscriptRef.current;
            if (callback) {
                callback(finalized);
            } else {
                setTranscript(finalized);
            }
        };

        recognition.addEventListener("start", onStart);
        recognition.addEventListener("end", onEnd);
        recognition.addEventListener("error", handleError);
        recognition.addEventListener("result", onResult);

        recognitionRef.current = recognition;

        return (): void => {
            recognition.removeEventListener("start", onStart);
            recognition.removeEventListener("end", onEnd);
            recognition.removeEventListener("error", handleError);
            recognition.removeEventListener("result", onResult);
            recognition.stop();
            if (recognitionRef.current === recognition) {
                recognitionRef.current = undefined;
            }
        };
    }, [enabled, supported, lang, continuous, SpeechRecognition]);

    const start = useCallback(() => {
        const recognition = recognitionRef.current;
        if (!enabled || !supported || !recognition) {
            return;
        }

        const startRecognition = (): void => {
            if (recognitionRef.current !== recognition) {
                return;
            }
            try {
                recognition.start();
            } catch (error) {
                logger.error("Error starting speech recognition:", error);
                if (
                    error instanceof DOMException &&
                    (error.name === "NotAllowedError" ||
                        error.name === "SecurityError")
                ) {
                    onErrorRef.current?.("not-allowed");
                }
            }
        };

        if (
            microphonePermissionGrantedRef.current ||
            typeof navigator.mediaDevices?.getUserMedia !== "function"
        ) {
            startRecognition();
            return;
        }
        if (startInProgressRef.current) {
            return;
        }

        startInProgressRef.current = true;
        void (async (): Promise<void> => {
            try {
                // Teams tabs require the host's media permission to be granted
                // through getUserMedia before Web Speech can use the microphone.
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: true,
                    video: false,
                });
                for (const track of stream.getTracks()) {
                    track.stop();
                }
                microphonePermissionGrantedRef.current = true;
                startRecognition();
            } catch (error) {
                const errorCode = microphoneErrorCode(error);
                logger.error("Error requesting microphone access:", error);
                onErrorRef.current?.(errorCode);
            } finally {
                startInProgressRef.current = false;
            }
        })();
    }, [enabled, supported]);

    const stop = useCallback(() => {
        if (!recognitionRef.current) {
            return;
        }
        // Optimistic UI update: the browser mic indicator may stop slightly later.
        setIsRecording(false);
        recognitionRef.current.stop();
    }, []);

    const clearTranscript = useCallback(() => {
        setTranscript("");
    }, []);

    return {
        start,
        stop,
        isRecording,
        transcript,
        clearTranscript,
        supported: enabled && supported,
    };
};
