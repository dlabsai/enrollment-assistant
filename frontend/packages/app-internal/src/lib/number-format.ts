const browserLocale = undefined;

export const formatLocaleNumber = (
    value: number,
    options?: Intl.NumberFormatOptions,
): string => value.toLocaleString(browserLocale, options);

export const makeLocaleNumberFormatter = (
    options?: Intl.NumberFormatOptions,
): Intl.NumberFormat => new Intl.NumberFormat(browserLocale, options);

export const formatUsdCost = (
    value: number | null | undefined,
): string => {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return "-";
    }
    if (value > 0 && value < 0.0001) {
        return `<$${formatLocaleNumber(0.0001, {
            minimumFractionDigits: 4,
            maximumFractionDigits: 4,
        })}`;
    }

    const fractionDigits = value > 0 && value < 0.01 ? 4 : 2;
    return `$${formatLocaleNumber(value, {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
    })}`;
};
