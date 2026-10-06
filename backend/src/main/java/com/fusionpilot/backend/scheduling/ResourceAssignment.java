package com.fusionpilot.backend.scheduling;

public record ResourceAssignment(
        int targetId,
        boolean allocated,
        int rank,
        double priorityScore,
        String reason
) {
}