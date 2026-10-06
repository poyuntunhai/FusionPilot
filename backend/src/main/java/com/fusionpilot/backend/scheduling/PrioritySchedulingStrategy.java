package com.fusionpilot.backend.scheduling;

import com.fusionpilot.backend.fusion.FusedTargetState;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;
import java.util.stream.IntStream;

@Component
public class PrioritySchedulingStrategy implements SchedulingStrategy {

    @Override
    public SchedulingPolicy policy() {
        return SchedulingPolicy.PRIORITY;
    }

    @Override
    public SchedulingResult schedule(
            List<FusedTargetState> targetStates,
            int availableResources,
            int timeStep
    ) {
        validateResources(availableResources);
        List<PriorityEntry> rankedTargets = targetStates.stream()
                .map(target -> new PriorityEntry(target, priorityScore(target)))
                .sorted(Comparator
                        .comparingDouble(PriorityEntry::score)
                        .reversed()
                        .thenComparingInt(entry -> entry.target().targetId()))
                .toList();
        int resourceCount = Math.min(availableResources, rankedTargets.size());

        List<ResourceAssignment> assignments = IntStream.range(0, rankedTargets.size())
                .mapToObj(index -> {
                    PriorityEntry entry = rankedTargets.get(index);
                    boolean allocated = index < resourceCount;
                    return new ResourceAssignment(
                            entry.target().targetId(),
                            allocated,
                            index + 1,
                            entry.score(),
                            reason(entry.target(), entry.score(), allocated)
                    );
                })
                .toList();
        return new SchedulingResult(
                timeStep,
                policy(),
                availableResources,
                assignments
        );
    }

    private double priorityScore(FusedTargetState target) {
        double uncertaintyScore = Math.min(1.0, target.uncertainty() / 10.0);
        double staleObservationScore = target.predictedOnly() ? 1.0 : 0.0;
        double trackingQualityScore = 1.0 - clamp(target.associationConfidence());
        double speed = Math.hypot(target.velocityX(), target.velocityY());
        double motionScore = Math.min(1.0, speed / 10.0);
        return 0.45 * uncertaintyScore
                + 0.30 * staleObservationScore
                + 0.20 * trackingQualityScore
                + 0.05 * motionScore;
    }

    private String reason(
            FusedTargetState target,
            double score,
            boolean allocated
    ) {
        String factors = String.format(
                "uncertainty=%.2f, predictedOnly=%s, trackQuality=%.2f, score=%.3f",
                target.uncertainty(),
                target.predictedOnly(),
                target.associationConfidence(),
                score
        );
        return (allocated ? "priority selected; " : "priority deferred; ") + factors;
    }

    private double clamp(double value) {
        return Math.max(0.0, Math.min(1.0, value));
    }

    private void validateResources(int availableResources) {
        if (availableResources < 0) {
            throw new IllegalArgumentException("availableResources must be non-negative");
        }
    }

    private record PriorityEntry(FusedTargetState target, double score) {
    }
}