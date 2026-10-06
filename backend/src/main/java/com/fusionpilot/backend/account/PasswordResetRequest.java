package com.fusionpilot.backend.account;

import jakarta.validation.constraints.NotBlank;

public record PasswordResetRequest(
        @NotBlank String login,
        @NotBlank String captchaId,
        @NotBlank String captchaAnswer
) {
}
