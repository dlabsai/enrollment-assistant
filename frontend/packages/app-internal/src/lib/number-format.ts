const browserLocale = undefined;

export const formatLocaleNumber = (
    value: number,
    options?: Intl.NumberFormatOptions,
): string => value.toLocaleString(browserLocale, options);

export const makeLocaleNumberFormatter = (
    options?: Intl.NumberFormatOptions,
): Intl.NumberFormat => new Intl.NumberFormat(browserLocale, options);

export const formatEstimatedUsdCost = (value: number | undefined): string => {
    if (value === undefined || !Number.isFinite(value)) {
        return "-";
    }
    if (value > 0 && value < 0.01) {
        return `<$${formatLocaleNumber(0.01, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }
    return `$${formatLocaleNumber(value, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
};
