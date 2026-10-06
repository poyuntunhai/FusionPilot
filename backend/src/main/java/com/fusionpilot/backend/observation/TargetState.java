package com.fusionpilot.backend.observation;

public record TargetState(
        int targetId,
        double x,
        double y,
        double velocityX,
        double velocityY,
        int timeStep
) {
    public TargetState advance(double deltaSeconds) {
        return new TargetState(
                targetId,
                x + velocityX * deltaSeconds,
                y + velocityY * deltaSeconds,
                velocityX,
                velocityY,
                timeStep + 1
        );
    }
}