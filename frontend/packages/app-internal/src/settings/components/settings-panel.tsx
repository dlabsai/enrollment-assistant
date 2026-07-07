import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { Input } from "@va/shared/components/ui/input";
import { Label } from "@va/shared/components/ui/label";
import { Spinner } from "@va/shared/components/ui/spinner";
import { Textarea } from "@va/shared/components/ui/textarea";
import { type JSX, useEffect, useState } from "react";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { PageSection } from "../../components/page-shell";
import { LoadingState } from "../../components/page-state";
import { fetchSettings, resetSettings, updateSettings } from "../lib/api";
import type { AppSettingsResponse, AppSettingsUpdate } from "../types";

interface SettingFieldConfig {
    key: keyof AppSettingsUpdate;
    label: string;
    type: "input" | "textarea";
}

const SETTING_FIELDS: SettingFieldConfig[] = [
    { key: "university_name", label: "University name", type: "input" },
    {
        key: "university_website_url",
        label: "University website URL",
        type: "input",
    },
    {
        key: "university_admissions_phone",
        label: "Admissions phone",
        type: "input",
    },
    {
        key: "university_transcripts_email",
        label: "Transcripts email",
        type: "input",
    },
    {
        key: "university_application_url",
        label: "Application URL",
        type: "input",
    },
    {
        key: "university_accreditation_url",
        label: "Accreditation URL",
        type: "input",
    },
    {
        key: "guardrails_blocked_message",
        label: "Guardrails blocked message",
        type: "textarea",
    },
];

export const SettingsPanel = (): JSX.Element => {
    const api = useAuthenticatedApi();
    const [settings, setSettings] = useState<AppSettingsResponse | undefined>();
    const [formValues, setFormValues] = useState<Record<string, string>>({});
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState<string | undefined>();

    useEffect(() => {
        const loadSettings = async (): Promise<void> => {
            setIsLoading(true);
            setError(undefined);
            try {
                const data = await fetchSettings(api);
                setSettings(data);
                setFormValues({ ...data.overrides });
            } catch (error_) {
                setError(
                    error_ instanceof Error
                        ? error_.message
                        : "Failed to load settings",
                );
            } finally {
                setIsLoading(false);
            }
        };
        void loadSettings();
    }, [api]);

    const handleInputChange = (key: string, value: string): void => {
        setFormValues((prev) => ({ ...prev, [key]: value }));
    };

    const hasChanges = (): boolean => {
        if (settings === undefined) {
            return false;
        }
        const currentOverrides = settings.overrides;
        for (const field of SETTING_FIELDS) {
            const formValue = formValues[field.key] ?? "";
            const overrideValue = currentOverrides[field.key] ?? "";
            if (formValue !== overrideValue) {
                return true;
            }
        }
        return false;
    };

    const hasAnyOverrides = (): boolean => {
        if (settings === undefined) {
            return false;
        }
        return Object.keys(settings.overrides).length > 0;
    };

    const handleSave = async (): Promise<void> => {
        if (settings === undefined) {
            return;
        }
        setIsSaving(true);
        setError(undefined);
        try {
            const updates: AppSettingsUpdate = {};
            for (const field of SETTING_FIELDS) {
                const formValue = formValues[field.key] ?? "";
                const overrideValue = settings.overrides[field.key] ?? "";
                if (formValue !== overrideValue) {
                    updates[field.key] = formValue === "" ? null : formValue;
                }
            }
            const data = await updateSettings(api, updates);
            setSettings(data);
            setFormValues({ ...data.overrides });
            toast.success("Settings saved");
        } catch (error_) {
            setError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to save settings",
            );
        } finally {
            setIsSaving(false);
        }
    };

    const handleReset = async (): Promise<void> => {
        setIsSaving(true);
        setError(undefined);
        try {
            const data = await resetSettings(api);
            setSettings(data);
            setFormValues({});
            toast.success("Settings reset to system values");
        } catch (error_) {
            setError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to reset settings",
            );
        } finally {
            setIsSaving(false);
        }
    };

    if (isLoading) {
        return <LoadingState />;
    }

    return (
        <PageSection className="space-y-6 py-6">
            <div className="mx-auto max-w-2xl">
                <Card>
                    <CardHeader>
                        <CardTitle>Application settings</CardTitle>
                        <CardDescription>
                            Override system-level settings. Leave fields empty
                            to use system defaults.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        {error !== undefined && (
                            <Alert variant="destructive">
                                <AlertDescription>{error}</AlertDescription>
                            </Alert>
                        )}

                        {SETTING_FIELDS.map((field) => {
                            const systemValue =
                                settings?.system[field.key] ?? "";
                            const formValue = formValues[field.key] ?? "";
                            const InputComponent =
                                field.type === "textarea" ? Textarea : Input;

                            return (
                                <div
                                    className="space-y-2"
                                    key={field.key}
                                >
                                    <Label htmlFor={field.key}>
                                        {field.label}
                                    </Label>
                                    <InputComponent
                                        disabled={isSaving}
                                        id={field.key}
                                        onChange={(event) => {
                                            handleInputChange(
                                                field.key,
                                                event.target.value,
                                            );
                                        }}
                                        placeholder={systemValue}
                                        value={formValue}
                                        {...(field.type === "textarea"
                                            ? { rows: 3 }
                                            : {})}
                                    />
                                    {formValue === "" && systemValue !== "" && (
                                        <p className="text-muted-foreground text-sm">
                                            System value: {systemValue}
                                        </p>
                                    )}
                                </div>
                            );
                        })}

                        <div className="flex gap-3 pt-4">
                            <Button
                                disabled={isSaving || !hasChanges()}
                                onClick={() => void handleSave()}
                            >
                                {isSaving ? (
                                    <>
                                        <Spinner data-icon="inline-start" />
                                        Saving...
                                    </>
                                ) : (
                                    "Save"
                                )}
                            </Button>
                            <Button
                                disabled={isSaving || !hasAnyOverrides()}
                                onClick={() => void handleReset()}
                                variant="outline"
                            >
                                Reset to system Values
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            </div>
        </PageSection>
    );
};
