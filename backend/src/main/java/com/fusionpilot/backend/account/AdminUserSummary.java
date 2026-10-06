package com.fusionpilot.backend.account;

import java.time.Instant;

public record AdminUserSummary(
        long userId,
        String username,
        String email,
        String displayName,
        String role,
        String status,
        Instant lastLoginAt,
        Instant createdAt
) {
}
