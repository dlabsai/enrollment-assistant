export const parsePositiveInt = (value: string, fallback: number): number => {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed) || parsed < 1) {
        return fallback;
    }
    return parsed;
};

export const parsePassThreshold = (value: string, fallback: number): number => {
    const parsed = Number.parseFloat(value);
    if (Number.isNaN(parsed) || parsed <= 0 || parsed > 1) {
        return fallback;
    }
    return parsed;
};

