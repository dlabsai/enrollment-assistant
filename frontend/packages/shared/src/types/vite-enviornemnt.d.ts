/// <reference types="vite/client" />

interface ImportMeta {
    readonly env: {
        [key: string]: string | boolean | undefined;
        readonly VITE_API_URL: string;
        readonly VITE_VISIBLE_BY_DEFAULT: string;
        readonly VITE_ENVIRONMENT: string;
        readonly VITE_UNIVERSITY_NAME: string;
        readonly VITE_UNIVERSITY_WEBSITE_URL: string;
        readonly VITE_ADMISSIONS_PHONE: string;
        readonly VITE_ADMISSIONS_PHONE_TEL: string;
        readonly VITE_PRIVACY_POLICY_URL: string;
        readonly VITE_TERMS_URL: string;
        readonly VITE_CONSENT_COMMUNICATIONS_URL: string;
        readonly VITE_AI_TERMS_URL: string;
        readonly VITE_PUBLIC_WIDGET_BASE_PATH: string;
        readonly VITE_TEAMS_SSO_ENABLED: string;
        readonly VITE_TEAMS_FORCE_MODE: string;
    };
}
