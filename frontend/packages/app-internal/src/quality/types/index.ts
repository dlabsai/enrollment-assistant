import type { TimeGranularity } from "../../lib/time-series";

export type QualityPlatform = "both" | "internal" | "public";

export interface QualityMetrics {
    assistant_responses: number;
    retry_observed_responses: number;
    retry_affected_responses: number;
    retry_attempts: number;
    blocked_responses: number;
    ratings: number;
    thumbs_up: number;
    thumbs_down: number;
    retry_affected_rate: number | null;
    blocked_rate: number | null;
    positive_rate: number | null;
    response_samples: number;
    median_response_seconds: number | null;
    p95_response_seconds: number | null;
    failed_generations: number;
    tracked_generation_attempts: number;
    generation_failure_rate: number | null;
}

export interface QualitySeriesPoint {
    bucket_start: string;
    bucket_end: string;
    retry_attempts: number;
    blocked_responses: number;
    thumbs_up: number;
    thumbs_down: number;
}

export interface QualityResponsivenessPoint {
    bucket_start: string;
    bucket_end: string;
    samples: number;
    median_seconds: number | null;
    p95_seconds: number | null;
}

interface QualityFailurePoint {
    bucket_start: string;
    bucket_end: string;
    tracked_attempts: number;
    failed_generations: number | null;
}

export interface QualityResponseTimeBucket {
    label: string;
    lower_bound: number;
    upper_bound: number | null;
    count: number;
    overflow: boolean;
}

export interface QualitySummary {
    summary: QualityMetrics;
    time_granularity: TimeGranularity;
    series: QualitySeriesPoint[];
    responsiveness_series: QualityResponsivenessPoint[];
    failure_series: QualityFailurePoint[];
    response_time_buckets: QualityResponseTimeBucket[];
}

export type QualityGuardrailStatus = "retried" | "blocked";
export type QualityFeedbackRating = "thumbs_up" | "thumbs_down";
