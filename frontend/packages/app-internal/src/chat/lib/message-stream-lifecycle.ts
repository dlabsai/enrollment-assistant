export type PrimaryMessageStreamOutcome =
    | "pending"
    | "assistant"
    | "generation_failure";

type TerminalPrimaryMessageStreamOutcome = Exclude<
    PrimaryMessageStreamOutcome,
    "pending"
>;

export const recordPrimaryMessageStreamOutcome = (
    current: PrimaryMessageStreamOutcome,
    next: TerminalPrimaryMessageStreamOutcome,
): TerminalPrimaryMessageStreamOutcome => {
    if (current !== "pending") {
        throw new TypeError("Message stream produced multiple primary outcomes");
    }
    return next;
};

export const assertPrimaryMessageStreamCompleted = (
    outcome: PrimaryMessageStreamOutcome,
): void => {
    if (outcome === "pending") {
        throw new TypeError("Message stream ended before a primary outcome");
    }
};
