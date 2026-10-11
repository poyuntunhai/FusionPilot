package com.fusionpilot.backend.notice;

import java.time.Instant;

/**
 * One entry on the notice board. {@code read} is per viewer, not a property of the message itself:
 * it is derived from fp_system_message_read for the authenticated caller and is always false for
 * anonymous visitors.
 */
public record SystemMessage(
        long messageId,
        String title,
        String body,
        String version,
        String level,
        Instant publishedAt,
        boolean read
) {
}
