package com.fusionpilot.backend.account;

/**
 * Signals that the caller is authenticated but not allowed to touch the requested resource.
 * Carries an optional message so run-ownership denials do not reuse the admin wording.
 */
public class ForbiddenException extends RuntimeException {

    public ForbiddenException() {
        super();
    }

    public ForbiddenException(String message) {
        super(message);
    }
}
