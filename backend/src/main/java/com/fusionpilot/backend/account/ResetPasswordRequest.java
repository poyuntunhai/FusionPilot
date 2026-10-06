package com.fusionpilot.backend.account;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record ResetPasswordRequest(
        @NotBlank String resetToken,
        @NotBlank
        @Size(min = 10, max = 100)
        @Pattern(
                regexp = "(?=.{10,100}$)(?:(?=.*[A-Za-z])(?=.*[0-9])|(?=.*[A-Za-z])(?=.*[^A-Za-z0-9])|(?=.*[0-9])(?=.*[^A-Za-z0-9])).*",
                message = "Password must be at least 10 characters and include at least two of letters, numbers, and symbols"
        )
        String newPassword
) {
}
