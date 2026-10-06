package com.fusionpilot.backend.account;

public record UserCredentials(
        long userId,
        String username,
        String email,
        String passwordHash,
        String displayName,
        String role,
        String status
) {
    public UserProfile profile() {
        return new UserProfile(userId, username, email, displayName, role, status);
    }
}
