const rawApiUrl: unknown = import.meta.env.VITE_API_URL;

if (typeof rawApiUrl !== "string" || rawApiUrl === "") {
    throw new Error("VITE_API_URL must be set");
}

export const API_URL = rawApiUrl;
export const ENVIRONMENT = String(import.meta.env.VITE_ENVIRONMENT ?? "");

export const UNIVERSITY_NAME = String(
    import.meta.env.VITE_UNIVERSITY_NAME ?? "Demo University",
);

const UNIVERSITY_WEBSITE_URL = String(
    import.meta.env.VITE_UNIVERSITY_WEBSITE_URL ?? "https://example.edu",
);

export const ADMISSIONS_PHONE = String(
    import.meta.env.VITE_ADMISSIONS_PHONE ?? "111.222.3333",
);

export const ADMISSIONS_PHONE_TEL = String(
    import.meta.env.VITE_ADMISSIONS_PHONE_TEL ??
        ADMISSIONS_PHONE.replaceAll(/\D/gu, ""),
);

export const PRIVACY_POLICY_URL = String(
    import.meta.env.VITE_PRIVACY_POLICY_URL ??
        `${UNIVERSITY_WEBSITE_URL}/privacy-policy/`,
);

export const TERMS_URL = String(
    import.meta.env.VITE_TERMS_URL ?? `${UNIVERSITY_WEBSITE_URL}/terms/`,
);

export const CONSENT_COMMUNICATIONS_URL = String(
    import.meta.env.VITE_CONSENT_COMMUNICATIONS_URL ??
        `${UNIVERSITY_WEBSITE_URL}/terms/#consent-electronic-communications`,
);

export const AI_TERMS_URL = String(
    import.meta.env.VITE_AI_TERMS_URL ??
        `${UNIVERSITY_WEBSITE_URL}/terms/#ai-terms`,
);
