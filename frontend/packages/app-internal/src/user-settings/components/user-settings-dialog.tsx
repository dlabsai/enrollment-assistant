import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import {
    Field,
    FieldDescription,
    FieldError,
    FieldGroup,
    FieldLabel,
} from "@va/shared/components/ui/field";
import { Spinner } from "@va/shared/components/ui/spinner";
import { Textarea } from "@va/shared/components/ui/textarea";
import { cn } from "@va/shared/lib/utils";
import {
    type JSX,
    type SyntheticEvent,
    useCallback,
    useId,
    useRef,
    useState,
} from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import { formatLocaleNumber } from "../../lib/number-format";
import { fetchUserSettings, saveUserSettings } from "../lib/api";
import { MAX_PERSONAL_INSTRUCTIONS_LENGTH, type UserSettings } from "../types";

interface UserSettingsDialogProps {
    onClose: () => void;
}

interface PersonalInstructionsFormProps {
    initialValue: string;
    loading: boolean;
    saving: boolean;
    error: string | undefined;
    onSave: (value: string) => void;
    onCancel: () => void;
}

const PersonalInstructionsForm = ({
    initialValue,
    loading,
    saving,
    error,
    onSave,
    onCancel,
}: PersonalInstructionsFormProps): JSX.Element => {
    const [value, setValue] = useState(initialValue);
    const fieldId = useId();
    const countId = useId();
    const errorId = `${countId}-error`;
    const formattedLimit = formatLocaleNumber(MAX_PERSONAL_INSTRUCTIONS_LENGTH);
    // Code points intentionally match Pydantic's string-length validation.
    // eslint-disable-next-line @typescript-eslint/no-misused-spread
    const { length } = [...value];
    const invalid = length > MAX_PERSONAL_INSTRUCTIONS_LENGTH;

    const handleSubmit = (event: SyntheticEvent<HTMLFormElement>): void => {
        event.preventDefault();
        if (!loading && !saving && !invalid && value !== initialValue) {
            onSave(value);
        }
    };

    return (
        <form
            className="flex flex-col gap-4"
            onSubmit={handleSubmit}
        >
            <FieldGroup>
                <Field
                    data-disabled={loading || saving}
                    data-invalid={invalid}
                >
                    <FieldLabel htmlFor={fieldId}>
                        Personal instructions
                    </FieldLabel>
                    <Textarea
                        aria-busy={loading}
                        aria-describedby={countId}
                        aria-errormessage={invalid ? errorId : undefined}
                        aria-invalid={invalid}
                        className={cn(
                            "max-h-[50svh] resize-y",
                            loading && "animate-pulse",
                        )}
                        disabled={loading || saving}
                        id={fieldId}
                        onChange={(event) => {
                            setValue(event.target.value);
                        }}
                        rows={8}
                        value={value}
                    />
                    <FieldDescription
                        className={cn(loading && "invisible")}
                        id={countId}
                    >
                        {formatLocaleNumber(length)} / {formattedLimit}
                    </FieldDescription>
                    {invalid && (
                        <FieldError id={errorId}>
                            Use no more than {formattedLimit} characters.
                        </FieldError>
                    )}
                </Field>
            </FieldGroup>
            {error !== undefined && (
                <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}
            <DialogFooter>
                <Button
                    disabled={saving}
                    onClick={onCancel}
                    type="button"
                    variant="outline"
                >
                    Cancel
                </Button>
                <Button
                    aria-busy={saving}
                    disabled={
                        loading || saving || invalid || value === initialValue
                    }
                    type="submit"
                >
                    {saving && <Spinner data-icon="inline-start" />}
                    Save
                </Button>
            </DialogFooter>
        </form>
    );
};

export const UserSettingsDialog = ({
    onClose,
}: UserSettingsDialogProps): JSX.Element => {
    const api = useAuthenticatedApi();
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string>();
    const savingRef = useRef(false);
    const load = useCallback(
        async (signal: AbortSignal) => fetchUserSettings(api, signal),
        [api],
    );
    const { data, error, refresh } = useAsyncData<
        UserSettings | undefined
    >({
        errorMessage: "Could not load your settings. Try again.",
        initialData: undefined,
        load,
    });

    const close = (): void => {
        if (!savingRef.current) {
            onClose();
        }
    };

    const setSavePending = (pending: boolean): void => {
        savingRef.current = pending;
        setSaving(pending);
    };

    const save = async (value: string): Promise<void> => {
        if (savingRef.current) {
            return;
        }
        setSavePending(true);
        setSaveError(undefined);
        try {
            await saveUserSettings(api, value);
            onClose();
        } catch {
            setSaveError("Could not save your settings. Try again.");
        } finally {
            setSavePending(false);
        }
    };

    return (
        <Dialog
            onOpenChange={(open) => {
                if (!open) {
                    close();
                }
            }}
            open
        >
            <DialogContent
                aria-describedby={undefined}
                className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-xl"
                showCloseButton={!saving}
            >
                <DialogHeader>
                    <DialogTitle>Settings</DialogTitle>
                </DialogHeader>
                {error === undefined ? (
                    <PersonalInstructionsForm
                        error={saveError}
                        // Remount once the account value arrives so the draft starts from it.
                        initialValue={data?.personal_instructions ?? ""}
                        key={data === undefined ? "pending" : "loaded"}
                        loading={data === undefined}
                        onCancel={close}
                        onSave={(value) => {
                            void save(value);
                        }}
                        saving={saving}
                    />
                ) : (
                    <>
                        <Alert variant="destructive">
                            <AlertDescription>
                                Could not load your settings.
                                <Button
                                    onClick={refresh}
                                    type="button"
                                    variant="outline"
                                >
                                    Try again
                                </Button>
                            </AlertDescription>
                        </Alert>
                        <DialogFooter>
                            <Button
                                onClick={close}
                                type="button"
                                variant="outline"
                            >
                                Cancel
                            </Button>
                        </DialogFooter>
                    </>
                )}
            </DialogContent>
        </Dialog>
    );
};
