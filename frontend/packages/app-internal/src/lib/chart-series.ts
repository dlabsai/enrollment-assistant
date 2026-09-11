import { useState } from "react";

interface VisibleChartSeries<T extends string> {
    hiddenSeries: ReadonlySet<string>;
    toggleSeries: (series: string) => void;
    visibleSeries: ReadonlySet<T>;
}

export const toggleVisibleSeries = <T extends string>(
    visibleSeries: ReadonlySet<T>,
    series: T,
): ReadonlySet<T> => {
    if (visibleSeries.has(series) && visibleSeries.size === 1) {
        return visibleSeries;
    }

    const nextVisibleSeries = new Set(visibleSeries);
    if (nextVisibleSeries.has(series)) {
        nextVisibleSeries.delete(series);
    } else {
        nextVisibleSeries.add(series);
    }
    return nextVisibleSeries;
};

export const useVisibleChartSeries = <T extends string>(
    dataKeys: readonly T[],
): VisibleChartSeries<T> => {
    const [visibleSeries, setVisibleSeries] = useState<ReadonlySet<T>>(
        () => new Set(dataKeys),
    );
    const toggleSeries = (series: string): void => {
        const dataKey = dataKeys.find((candidate) => candidate === series);
        if (dataKey === undefined) {
            return;
        }
        setVisibleSeries((current) => toggleVisibleSeries(current, dataKey));
    };

    return {
        hiddenSeries: new Set<string>(
            dataKeys.filter((dataKey) => !visibleSeries.has(dataKey)),
        ),
        toggleSeries,
        visibleSeries,
    };
};
