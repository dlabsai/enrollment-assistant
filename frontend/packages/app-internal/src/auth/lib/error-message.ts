const DEFAULT_AUTH_ERROR_MESSAGE =
    "Something went wrong. Please try again later.";

export const getAuthFormErrorMessage = (detail?: string): string => {
    switch (detail) {
        case "Incorrect email or password": {
            return "The email or password you entered is incorrect. Please try again.";
        }
        case "Inactive user": {
            return "This account is inactive. Please contact the person who manages access to this app.";
        }
        case "Invalid registration token": {
            return "That registration token isn't valid. Check the token and try again.";
        }
        case "Email already registered": {
            return "An account with this email already exists. Try signing in instead.";
        }
        default: {
            return DEFAULT_AUTH_ERROR_MESSAGE;
        }
    }
};
