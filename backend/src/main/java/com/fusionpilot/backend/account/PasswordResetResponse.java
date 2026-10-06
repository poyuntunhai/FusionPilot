package com.fusionpilot.backend.account;

public record PasswordResetResponse(
        String message,
        String developmentResetToken
) {
}
