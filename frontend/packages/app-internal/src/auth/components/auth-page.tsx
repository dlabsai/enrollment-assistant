import { Alert, AlertDescription } from "@va/shared/components/ui/alert";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    Form,
    FormControl,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
} from "@va/shared/components/ui/form";
import { Input } from "@va/shared/components/ui/input";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { useAuth } from "../contexts/auth-context";
import { loginUser, registerUser } from "../lib/api";

interface FormState {
    name: string;
    email: string;
    password: string;
    confirmPassword: string;
    registration_token: string;
}

type Mode = "login" | "register";

const initialFormState = (): FormState => ({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
    registration_token: "",
});

export const AuthPage = (): JSX.Element => {
    const {
        authenticate,
        authError,
        clearAuthError,
        sessionExpired,
        signInWithTeamsSso,
        teamsAuthMode,
        teamsSsoEnabled,
        teamsSsoLoading,
    } = useAuth();
    const [mode, setMode] = useState<Mode>("login");
    const [error, setError] = useState<string | undefined>();
    const form = useForm<FormState>({
        defaultValues: initialFormState(),
    });
    const { isSubmitting } = form.formState;
    const activeMode = sessionExpired ? "login" : mode;
    const teamsOnlyMode =
        activeMode === "login" &&
        teamsSsoEnabled &&
        teamsAuthMode !== "outside";
    const displayedError = error ?? authError;

    const validatePasswords = useCallback(
        (values: FormState): string | undefined => {
            const validationMessages =
                activeMode === "register"
                    ? [
                          values.password !== values.confirmPassword &&
                              "Passwords do not match",
                          values.password.length < 12 &&
                              "Password must be at least 12 characters",
                          !/[A-Z]/u.test(values.password) &&
                              "Password must include at least one uppercase letter",
                          !/[a-z]/u.test(values.password) &&
                              "Password must include at least one lowercase letter",
                          !/\d/u.test(values.password) &&
                              "Password must include at least one number",
                      ]
                    : [];

            return validationMessages.find(
                (message): message is string => typeof message === "string",
            );
        },
        [activeMode],
    );

    const title = useMemo(
        () =>
            teamsOnlyMode
                ? "Continue in Microsoft Teams"
                : activeMode === "login"
                  ? "Sign in to continue"
                  : "Register with registration token",
        [activeMode, teamsOnlyMode],
    );

    const helperText = useMemo(
        () =>
            teamsOnlyMode
                ? "Use your Microsoft Teams account to sign in to the internal app."
                : activeMode === "login"
                  ? "Use the email and password you registered with."
                  : "Provide your name, email, password, and the registration token you were given.",
        [activeMode, teamsOnlyMode],
    );

    const isBusy = isSubmitting || teamsSsoLoading;

    let submitLabel = "Register";
    if (isBusy) {
        submitLabel = "Working...";
    } else if (activeMode === "login") {
        submitLabel = "Login";
    }

    const handleSubmit = useCallback(
        async (values: FormState) => {
            setError(undefined);
            clearAuthError();

            const passwordError = validatePasswords(values);
            if (passwordError !== undefined) {
                form.setError("password", {
                    message: passwordError,
                    type: "manual",
                });
                return;
            }

            try {
                await (activeMode === "login"
                    ? loginUser({
                          email: values.email,
                          password: values.password,
                      })
                    : registerUser({
                          name: values.name,
                          email: values.email,
                          password: values.password,
                          confirm_password: values.confirmPassword,
                          registration_token: values.registration_token,
                      }));

                await authenticate();
            } catch (error) {
                const message =
                    error instanceof Error
                        ? error.message
                        : "Authentication failed";
                setError(message);
            }
        },
        [authenticate, clearAuthError, form, activeMode, validatePasswords],
    );

    const toggleMode = useCallback(() => {
        setMode((prev) => (prev === "login" ? "register" : "login"));
        form.reset(initialFormState());
        setError(undefined);
        clearAuthError();
    }, [clearAuthError, form]);

    useEffect(() => {
        if (sessionExpired) {
            form.reset(initialFormState());
        }
    }, [form, sessionExpired]);

    const handleTeamsSsoSignIn = useCallback(async () => {
        setError(undefined);
        clearAuthError();

        try {
            await signInWithTeamsSso();
        } catch (error) {
            const message =
                error instanceof Error
                    ? error.message
                    : "Microsoft Teams authentication failed";
            setError(message);
        }
    }, [clearAuthError, signInWithTeamsSso]);

    return (
        <div className="bg-background text-foreground flex min-h-screen flex-col">
            {sessionExpired && (
                <div className="px-4 pt-4">
                    <Alert>
                        <AlertDescription>
                            Your session has expired — please sign in again.
                        </AlertDescription>
                    </Alert>
                </div>
            )}
            <div className="flex flex-1 items-center justify-center px-4 py-6">
                <Card className="w-full max-w-sm">
                    <CardHeader>
                        <CardTitle className="text-2xl font-semibold">
                            {title}
                        </CardTitle>
                        <CardDescription className="text-muted-foreground">
                            {helperText}
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        {teamsOnlyMode ? (
                            <div className="space-y-4">
                                {displayedError !== undefined &&
                                    displayedError !== "" && (
                                        <Alert variant="destructive">
                                            <AlertDescription>
                                                {displayedError}
                                            </AlertDescription>
                                        </Alert>
                                    )}

                                <Button
                                    className="w-full"
                                    disabled={isBusy}
                                    onClick={() => {
                                        void handleTeamsSsoSignIn();
                                    }}
                                    type="button"
                                >
                                    {teamsSsoLoading
                                        ? "Connecting to Teams..."
                                        : "Continue with Microsoft Teams"}
                                </Button>
                            </div>
                        ) : (
                            <Form {...form}>
                                <form
                                    className="space-y-4"
                                    onSubmit={(event) => {
                                        void form.handleSubmit(handleSubmit)(
                                            event,
                                        );
                                    }}
                                >
                                    {activeMode === "register" && (
                                        <FormField
                                            control={form.control}
                                            name="name"
                                            render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>Name</FormLabel>
                                                    <FormControl>
                                                        <Input
                                                            {...field}
                                                            disabled={isBusy}
                                                            placeholder="Jane Doe"
                                                            required
                                                        />
                                                    </FormControl>
                                                    <FormMessage />
                                                </FormItem>
                                            )}
                                        />
                                    )}

                                    <FormField
                                        control={form.control}
                                        name="email"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>Email</FormLabel>
                                                <FormControl>
                                                    <Input
                                                        {...field}
                                                        disabled={isBusy}
                                                        placeholder="you@example.com"
                                                        required
                                                        type="email"
                                                    />
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />

                                    <FormField
                                        control={form.control}
                                        name="password"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>Password</FormLabel>
                                                <FormControl>
                                                    <Input
                                                        {...field}
                                                        disabled={isBusy}
                                                        required
                                                        type="password"
                                                    />
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />

                                    {activeMode === "register" && (
                                        <FormField
                                            control={form.control}
                                            name="confirmPassword"
                                            render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>
                                                        Confirm password
                                                    </FormLabel>
                                                    <FormControl>
                                                        <Input
                                                            {...field}
                                                            disabled={isBusy}
                                                            required
                                                            type="password"
                                                        />
                                                    </FormControl>
                                                    <FormMessage />
                                                </FormItem>
                                            )}
                                        />
                                    )}

                                    {activeMode === "register" && (
                                        <FormField
                                            control={form.control}
                                            name="registration_token"
                                            render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>
                                                        Registration token
                                                    </FormLabel>
                                                    <FormControl>
                                                        <Input
                                                            {...field}
                                                            disabled={isBusy}
                                                            required
                                                            type="password"
                                                        />
                                                    </FormControl>
                                                    <FormMessage />
                                                </FormItem>
                                            )}
                                        />
                                    )}

                                    {displayedError !== undefined &&
                                        displayedError !== "" && (
                                            <Alert variant="destructive">
                                                <AlertDescription>
                                                    {displayedError}
                                                </AlertDescription>
                                            </Alert>
                                        )}

                                    {teamsSsoEnabled &&
                                        teamsAuthMode !== "outside" &&
                                        activeMode === "login" && (
                                            <Button
                                                className="w-full"
                                                disabled={isBusy}
                                                onClick={() => {
                                                    void handleTeamsSsoSignIn();
                                                }}
                                                type="button"
                                                variant="outline"
                                            >
                                                {teamsSsoLoading
                                                    ? "Connecting to Teams..."
                                                    : "Continue with Microsoft Teams"}
                                            </Button>
                                        )}

                                    <div className="flex items-center justify-between gap-4">
                                        <Button
                                            className="flex-1"
                                            disabled={isBusy}
                                            type="submit"
                                        >
                                            {submitLabel}
                                        </Button>
                                        {!sessionExpired && (
                                            <Button
                                                disabled={isBusy}
                                                onClick={toggleMode}
                                                type="button"
                                                variant="outline"
                                            >
                                                {activeMode === "login"
                                                    ? "Need an account? Register"
                                                    : "Have an account? Login"}
                                            </Button>
                                        )}
                                    </div>
                                </form>
                            </Form>
                        )}
                    </CardContent>
                </Card>
            </div>
        </div>
    );
};
