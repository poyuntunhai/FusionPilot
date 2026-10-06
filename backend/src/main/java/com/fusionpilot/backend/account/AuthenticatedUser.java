package com.fusionpilot.backend.account;

public record AuthenticatedUser(
        long userId,
        String username,
        String email,
        String displayName,
        String role,
        String status
) {
    public boolean isAdmin() {
        return "ADMIN".equals(role) && "ACTIVE".equals(status);
    }
}
