import { getTimeSeriesBucketRange } from "../../lib/time-series";
import type { FetchedQualitySummary } from "./api";

type QualityDrilldownRange = FetchedQualitySummary["appliedRange"] & {
    endBefore?: string;
};

interface BoundedQualityPoint {
    bucket_start: string;
    bucket_end: string;
}

export const getQualityDrilldownRange = (
    appliedRange: QualityDrilldownRange,
    point?: BoundedQualityPoint,
): QualityDrilldownRange => {
    if (point === undefined) {
        return appliedRange;
    }

    return getTimeSeriesBucketRange(point);
};

interface ResponseTimeBounds {
    lower_bound: number;
    upper_bound: number | null;
}

interface ResponsivenessDurationSearch {
    minGenerationTimeMs: number;
    maxGenerationTimeMs: number | undefined;
}

export const getResponsivenessDurationSearch = (
    bucket?: ResponseTimeBounds,
): ResponsivenessDurationSearch => ({
    minGenerationTimeMs: (bucket?.lower_bound ?? 0) * 1000,
    maxGenerationTimeMs:
        bucket?.upper_bound === null || bucket?.upper_bound === undefined
            ? undefined
            : bucket.upper_bound * 1000,
});
