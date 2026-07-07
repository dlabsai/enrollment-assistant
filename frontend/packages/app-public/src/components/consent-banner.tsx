import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import { Input } from "@va/shared/components/ui/input";
import {
    AI_TERMS_URL,
    CONSENT_COMMUNICATIONS_URL,
    PRIVACY_POLICY_URL,
    TERMS_URL,
    UNIVERSITY_NAME,
} from "@va/shared/config";
import { type ChangeEvent, type JSX, type SyntheticEvent, useState } from "react";

import { submitConsentData } from "../lib/consent-api";
import { getChatId, setConsentData } from "../lib/storage";

interface ConsentFormValues {
    firstName: string;
    lastName: string;
    email: string;
    phone: string;
    zip: string;
}

interface ConsentBannerProps {
    onAccept: () => void;
    onDecline: () => void;
}

type ConsentFormErrors = Partial<Record<keyof ConsentFormValues, string>>;

const initialValues: ConsentFormValues = {
    firstName: "",
    lastName: "",
    email: "",
    phone: "",
    zip: "",
};

const formatPhoneNumber = (value: string): string => {
    const numbers = value.replaceAll(/\D/gu, "");
    if (numbers.length === 0) {
        return "";
    }
    if (numbers.length <= 3) {
        return `(${numbers}`;
    }
    if (numbers.length <= 6) {
        return `(${numbers.slice(0, 3)}) ${numbers.slice(3)}`;
    }
    return `(${numbers.slice(0, 3)}) ${numbers.slice(3, 6)}-${numbers.slice(6, 10)}`;
};

const formatZipCode = (value: string): string => value.replaceAll(/\D/gu, "").slice(0, 5);

const validate = (values: ConsentFormValues): ConsentFormErrors => {
    const errors: ConsentFormErrors = {};
    if (values.firstName.trim().length < 2) {
        errors.firstName = "First name must be at least 2 characters";
    }
    if (values.lastName.trim().length < 2) {
        errors.lastName = "Last name must be at least 2 characters";
    }
    if (!/^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/iu.test(values.email.trim())) {
        errors.email = "Please enter a valid email";
    }
    if (values.phone.length !== 10) {
        errors.phone = "Phone must be 10 digits";
    }
    if (values.zip.length !== 5) {
        errors.zip = "Zip must be 5 digits";
    }
    return errors;
};

const FieldError = ({ message }: { message: string | undefined }): JSX.Element | null => {
    if (message === undefined) {
        return null;
    }
    return <p className="text-destructive mt-1 text-xs">{message}</p>;
};

export const ConsentBanner = ({
    onAccept,
    onDecline,
}: ConsentBannerProps): JSX.Element => {
    const [values, setValues] = useState(initialValues);
    const [errors, setErrors] = useState<ConsentFormErrors>({});
    const [submitError, setSubmitError] = useState<string | undefined>();
    const [isSubmitting, setIsSubmitting] = useState(false);

    const updateValue = (field: keyof ConsentFormValues, value: string): void => {
        setValues((current) => ({ ...current, [field]: value }));
        setErrors((current) => ({ ...current, [field]: undefined }));
        setSubmitError(undefined);
    };

    const handleSubmit = async (event: SyntheticEvent<HTMLFormElement>): Promise<void> => {
        event.preventDefault();

        const nextErrors = validate(values);
        setErrors(nextErrors);
        if (Object.keys(nextErrors).length > 0) {
            return;
        }

        const consentData = {
            firstName: values.firstName.trim(),
            lastName: values.lastName.trim(),
            email: values.email.trim(),
            phone: values.phone,
            zip: values.zip,
            timestamp: Date.now(),
        };

        setIsSubmitting(true);
        const result = await submitConsentData(consentData, getChatId());

        setIsSubmitting(false);
        if (result.success) {
            setConsentData(consentData);
            onAccept();
            return;
        }

        setSubmitError(result.error ?? "Failed to submit consent. Please try again.");
    };

    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>Before you continue</CardTitle>
            </CardHeader>
            <form onSubmit={(event) => void handleSubmit(event)}>
                <CardContent className="space-y-3">
                    <div>
                        <Input
                            aria-invalid={errors.firstName !== undefined}
                            autoComplete="given-name"
                            onChange={(event: ChangeEvent<HTMLInputElement>) => {
                                updateValue("firstName", event.target.value);
                            }}
                            placeholder="First name"
                            value={values.firstName}
                        />
                        <FieldError message={errors.firstName} />
                    </div>
                    <div>
                        <Input
                            aria-invalid={errors.lastName !== undefined}
                            autoComplete="family-name"
                            onChange={(event: ChangeEvent<HTMLInputElement>) => {
                                updateValue("lastName", event.target.value);
                            }}
                            placeholder="Last name"
                            value={values.lastName}
                        />
                        <FieldError message={errors.lastName} />
                    </div>
                    <div>
                        <Input
                            aria-invalid={errors.email !== undefined}
                            autoComplete="email"
                            onChange={(event: ChangeEvent<HTMLInputElement>) => {
                                updateValue("email", event.target.value);
                            }}
                            placeholder="Email"
                            type="email"
                            value={values.email}
                        />
                        <FieldError message={errors.email} />
                    </div>
                    <div>
                        <Input
                            aria-invalid={errors.phone !== undefined}
                            autoComplete="tel"
                            inputMode="tel"
                            onChange={(event: ChangeEvent<HTMLInputElement>) => {
                                updateValue(
                                    "phone",
                                    event.target.value.replaceAll(/\D/gu, "").slice(0, 10),
                                );
                            }}
                            placeholder="Phone"
                            type="tel"
                            value={formatPhoneNumber(values.phone)}
                        />
                        <FieldError message={errors.phone} />
                    </div>
                    <div>
                        <Input
                            aria-invalid={errors.zip !== undefined}
                            autoComplete="postal-code"
                            inputMode="numeric"
                            onChange={(event: ChangeEvent<HTMLInputElement>) => {
                                updateValue("zip", formatZipCode(event.target.value));
                            }}
                            placeholder="Zip"
                            type="text"
                            value={values.zip}
                        />
                        <FieldError message={errors.zip} />
                    </div>
                    <p className="text-muted-foreground text-xs leading-relaxed">
                        I consent to the recording of my interaction with this AI Enrollment
                        Assistant and agree to {UNIVERSITY_NAME}&apos;s{" "}
                        <a
                            className="hover:text-foreground underline"
                            href={PRIVACY_POLICY_URL}
                            rel="noopener noreferrer"
                            target="_blank"
                        >
                            Privacy Policy
                        </a>
                        , the website and apps{" "}
                        <a
                            className="hover:text-foreground underline"
                            href={TERMS_URL}
                            rel="noopener noreferrer"
                            target="_blank"
                        >
                            Terms and Conditions
                        </a>
                        ,{" "}
                        <a
                            className="hover:text-foreground underline"
                            href={CONSENT_COMMUNICATIONS_URL}
                            rel="noopener noreferrer"
                            target="_blank"
                        >
                            Consent to Electronic Communications
                        </a>
                        , and the{" "}
                        <a
                            className="hover:text-foreground underline"
                            href={AI_TERMS_URL}
                            rel="noopener noreferrer"
                            target="_blank"
                        >
                            AI Enrollment Assistant Terms and Conditions
                        </a>
                        . By starting the enrollment assistant, I agree to receive email, SMS and
                        text communications, and phone calls and voicemails from {UNIVERSITY_NAME}
                        at the contact information provided to {UNIVERSITY_NAME}.
                    </p>
                    {submitError !== undefined && (
                        <p className="text-destructive text-xs">{submitError}</p>
                    )}
                </CardContent>
                <CardFooter className="mt-4 justify-end gap-2">
                    <Button
                        disabled={isSubmitting}
                        onClick={onDecline}
                        size="sm"
                        type="button"
                        variant="outline"
                    >
                        Decline
                    </Button>
                    <Button
                        disabled={isSubmitting}
                        size="sm"
                        type="submit"
                    >
                        Accept
                    </Button>
                </CardFooter>
            </form>
        </Card>
    );
};
