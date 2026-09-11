import type {
    Finding,
    FlagDetail,
    FlagSummary,
    ScreeningDetail,
} from "../src/compliance/types";

export const screening: ScreeningDetail = {
    id: "11111111-1111-4111-8111-111111111111",
    created_at: "2026-09-02T12:00:00Z",
    author: "Reviewer",
    start: "2026-09-01T04:00:00Z",
    end: "2026-09-02T03:59:59Z",
    instructions_version_id: "22222222-2222-4222-8222-222222222222",
    admission_error: null,
    messages: 10,
    conversations: 5,
    screened: 10,
    screened_conversations: 5,
    pending: 0,
    errors: 0,
    error_conversations: 0,
    deleted: 0,
    findings: 1,
    needs_review: 1,
    failures: [],
    instructions: {
        id: "22222222-2222-4222-8222-222222222222",
        number: 1,
        created_at: "2026-09-01T00:00:00Z",
        author: "Instruction owner",
        content: "Do not promise admission.",
    },
};
export const finding: Finding = {
    id: "44444444-4444-4444-8444-444444444444",
    title: "Possible promise",
    explanation:
        "The message appears to promise admission, which conflicts with the requirement not to promise admission. Confirm whether the stated exception applies.",
    evidence: "Admission is guaranteed.",
    state: "needs_review",
    revision: 0,
    decisions: [],
};
export const flagSummary: FlagSummary = {
    id: finding.id,
    title: finding.title,
    chat: "Admission question",
    message_at: screening.start,
    state: "needs_review",
};
export const flagDetail: FlagDetail = {
    chat: "Admission question",
    message_id: "66666666-6666-4666-8666-666666666666",
    message_at: screening.start,
    error: null,
    transcript: [],
    flag: finding,
};
