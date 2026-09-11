import assert from "node:assert/strict";

import { describe, it } from "vitest";

import { getAuthFormErrorMessage } from "../src/auth/lib/error-message";

describe("auth form error messages", () => {
    it("gives clear next steps for known sign-in failures", () => {
        assert.equal(
            getAuthFormErrorMessage("Incorrect email or password"),
            "The email or password you entered is incorrect. Please try again.",
        );
        assert.equal(
            getAuthFormErrorMessage("Inactive user"),
            "This account is inactive. Please contact the person who manages access to this app.",
        );
    });

    it("gives clear next steps for known registration failures", () => {
        assert.equal(
            getAuthFormErrorMessage("Invalid registration token"),
            "That registration token isn't valid. Check the token and try again.",
        );
        assert.equal(
            getAuthFormErrorMessage("Email already registered"),
            "An account with this email already exists. Try signing in instead.",
        );
        assert.equal(
            getAuthFormErrorMessage("Password registration is not enabled"),
            "Registration is not available. Sign in with an existing account.",
        );
    });

    it("uses a neutral message for other failures", () => {
        assert.equal(
            getAuthFormErrorMessage("Unexpected response"),
            "Something went wrong. Please try again later.",
        );
        assert.equal(
            getAuthFormErrorMessage(),
            "Something went wrong. Please try again later.",
        );
    });
});
