package com.fusionpilot.backend.account;

public record UserProfile(
        long userId,
        String username,
        String email,
        String displayName,
        String role,
        String status
) {
}
