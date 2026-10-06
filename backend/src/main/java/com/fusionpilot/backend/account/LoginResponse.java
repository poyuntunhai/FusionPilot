package com.fusionpilot.backend.account;

import java.time.Instant;

public record LoginResponse(
        String accessToken,
        Instant expiresAt,
        UserProfile user
) {
}
