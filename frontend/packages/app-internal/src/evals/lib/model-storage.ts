const MODEL_CONFIG_STORAGE_KEY = "va.internal.evals.model-config";
const MODEL_FAVORITES_STORAGE_KEY = "va.internal.evals.model-favorites";
const MODEL_PRESETS_STORAGE_KEY = "va.internal.evals.model-presets";

interface StoredEvalModelConfig {
    chatbotModel?: string;
    guardrailModel?: string;
    evaluationModel?: string;
}

export interface EvalModelPreset {
    name: string;
    chatbotModel?: string;
    guardrailModel?: string;
    evaluationModel?: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null;

export const readStoredModelConfig = (): StoredEvalModelConfig | undefined => {
    if (typeof window === "undefined") {
        return undefined;
    }
    const stored = window.localStorage.getItem(MODEL_CONFIG_STORAGE_KEY);
    if (stored === null || stored === "") {
        return undefined;
    }
    try {
        const parsed: unknown = JSON.parse(stored);
        if (!isRecord(parsed)) {
            return undefined;
        }
        const safeParsed: StoredEvalModelConfig = {};
        if (typeof parsed.chatbotModel === "string") {
            safeParsed.chatbotModel = parsed.chatbotModel;
        }
        if (typeof parsed.guardrailModel === "string") {
            safeParsed.guardrailModel = parsed.guardrailModel;
        }
        if (typeof parsed.evaluationModel === "string") {
            safeParsed.evaluationModel = parsed.evaluationModel;
        }
        return safeParsed;
    } catch {
        return undefined;
    }
};

export const readStoredModelFavorites = (): string[] => {
    if (typeof window === "undefined") {
        return [];
    }
    const stored = window.localStorage.getItem(MODEL_FAVORITES_STORAGE_KEY);
    if (stored === null || stored === "") {
        return [];
    }
    try {
        const parsed: unknown = JSON.parse(stored);
        if (!Array.isArray(parsed)) {
            return [];
        }
        return parsed.filter(
            (value): value is string => typeof value === "string",
        );
    } catch {
        return [];
    }
};

export const readStoredModelPresets = (): EvalModelPreset[] => {
    if (typeof window === "undefined") {
        return [];
    }
    const stored = window.localStorage.getItem(MODEL_PRESETS_STORAGE_KEY);
    if (stored === null || stored === "") {
        return [];
    }
    try {
        const parsed: unknown = JSON.parse(stored);
        if (!Array.isArray(parsed)) {
            return [];
        }
        const presets: EvalModelPreset[] = [];
        for (const entry of parsed) {
            if (isRecord(entry)) {
                const nameValue = entry.name;
                const name =
                    typeof nameValue === "string" ? nameValue.trim() : "";
                if (name !== "") {
                    const preset: EvalModelPreset = { name };
                    if (
                        typeof entry.chatbotModel === "string" &&
                        entry.chatbotModel !== ""
                    ) {
                        preset.chatbotModel = entry.chatbotModel;
                    }
                    if (
                        typeof entry.guardrailModel === "string" &&
                        entry.guardrailModel !== ""
                    ) {
                        preset.guardrailModel = entry.guardrailModel;
                    }
                    if (
                        typeof entry.evaluationModel === "string" &&
                        entry.evaluationModel !== ""
                    ) {
                        preset.evaluationModel = entry.evaluationModel;
                    }
                    presets.push(preset);
                }
            }
        }
        return presets;
    } catch {
        window.localStorage.removeItem(MODEL_PRESETS_STORAGE_KEY);
        return [];
    }
};

export const writeStoredModelConfig = (
    payload: StoredEvalModelConfig,
): void => {
    if (typeof window === "undefined") {
        return;
    }
    window.localStorage.setItem(
        MODEL_CONFIG_STORAGE_KEY,
        JSON.stringify(payload),
    );
};

export const writeStoredModelFavorites = (favorites: string[]): void => {
    if (typeof window === "undefined") {
        return;
    }
    window.localStorage.setItem(
        MODEL_FAVORITES_STORAGE_KEY,
        JSON.stringify(favorites),
    );
};

export const writeStoredModelPresets = (presets: EvalModelPreset[]): void => {
    if (typeof window === "undefined") {
        return;
    }
    window.localStorage.setItem(
        MODEL_PRESETS_STORAGE_KEY,
        JSON.stringify(presets),
    );
};
