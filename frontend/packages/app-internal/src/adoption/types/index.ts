export interface AdoptionDaily {
    date: string;
    daily_active_users: number;
    monthly_active_users: number;
}

export interface AdoptionSummary {
    latest_daily_active_users: number;
    monthly_active_users: number;
    average_daily_active_users: number;
    stickiness: number;
    daily: AdoptionDaily[];
}
