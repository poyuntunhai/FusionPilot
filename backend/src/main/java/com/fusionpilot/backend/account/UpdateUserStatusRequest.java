package com.fusionpilot.backend.account;

import jakarta.validation.constraints.NotBlank;

public record UpdateUserStatusRequest(@NotBlank String status) {
}
