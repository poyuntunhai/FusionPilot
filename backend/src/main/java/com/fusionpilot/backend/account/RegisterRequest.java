package com.fusionpilot.backend.account;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
        @NotBlank @Size(min = 3, max = 50) String username,
        @NotBlank @Email @Size(max = 190) String email,
        @NotBlank
        @Size(min = 10, max = 100)
        @Pattern(
                regexp = "(?=.{10,100}$)(?:(?=.*[A-Za-z])(?=.*[0-9])|(?=.*[A-Za-z])(?=.*[^A-Za-z0-9])|(?=.*[0-9])(?=.*[^A-Za-z0-9])).*",
                message = "Password must be at least 10 characters and include at least two of letters, numbers, and symbols"
        )
        String password,
        @NotBlank @Size(max = 80) String displayName,
        @NotBlank String captchaId,
        @NotBlank String captchaAnswer
) {
}
