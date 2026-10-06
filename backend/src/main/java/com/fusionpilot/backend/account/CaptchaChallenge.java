package com.fusionpilot.backend.account;

import java.time.Instant;

public record CaptchaChallenge(
        String challengeId,
        String question,
        Instant expiresAt
) {
}
