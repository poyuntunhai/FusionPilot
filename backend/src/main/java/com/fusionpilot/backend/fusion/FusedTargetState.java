package com.fusionpilot.backend.fusion;

public record FusedTargetState(
        int targetId,
        double x,
        double y,
        double velocityX,
        double velocityY,
        double uncertainty,
        double associationConfidence,
        int timeStep,
        boolean predictedOnly
) {
}