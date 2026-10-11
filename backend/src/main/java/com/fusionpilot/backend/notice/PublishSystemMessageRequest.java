package com.fusionpilot.backend.notice;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/**
 * Admin payload for publishing a release note. {@code version} and {@code level} are optional;
 * {@code level} defaults to INFO so the common case is a two-field JSON body. The level is
 * constrained here rather than in the service so a typo comes back as a 400 with a readable
 * message instead of falling through to the catch-all 500.
 */
public record PublishSystemMessageRequest(
        @NotBlank @Size(max = 200) String title,
        @NotBlank @Size(max = 2000) String body,
        @Size(max = 60) String version,
        @Pattern(regexp = "(?i)^(INFO|UPDATE|WARNING)?$", message = "must be INFO, UPDATE or WARNING")
        String level
) {
}
