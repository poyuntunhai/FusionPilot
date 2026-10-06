package com.fusionpilot.backend.api;

import java.time.Instant;
import java.util.List;

public record ErrorResponse(
        boolean success,
        String code,
        String message,
        List<String> details,
        Instant timestamp
) {
    public static ErrorResponse of(String code, String message, List<String> details) {
        return new ErrorResponse(false, code, message, details, Instant.now());
    }
}
