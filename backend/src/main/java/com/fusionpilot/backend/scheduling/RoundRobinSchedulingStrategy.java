package com.fusionpilot.backend.scheduling;

import com.fusionpilot.backend.fusion.FusedTargetState;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;
import java.util.stream.IntStream;

@Component
public class RoundRobinSchedulingStrategy implements SchedulingStrategy {

    @Override
    public SchedulingPolicy policy() {
        return SchedulingPolicy.ROUND_ROBIN;
    }

    @Override
    public SchedulingResult schedule(
            List<FusedTargetState> targetStates,
            int availableResources,
            int timeStep
    ) {
        validateResources(availableResources);
        List<FusedTargetState> orderedTargets = targetStates.stream()
                .sorted(Comparator.comparingInt(FusedTargetState::targetId))
                .toList();
        int resourceCount = Math.min(availableResources, orderedTargets.size());
        int startIndex = orderedTargets.isEmpty()
                ? 0
                : Math.floorMod(timeStep, orderedTargets.size());

        List<ResourceAssignment> assignments = IntStream.range(0, orderedTargets.size())
                .mapToObj(index -> {
                    FusedTargetState target = orderedTargets.get(index);
                    int roundRobinRank = Math.floorMod(index - startIndex, orderedTargets.size());
                    boolean allocated = roundRobinRank < resourceCount;
                    return new ResourceAssignment(
                            target.targetId(),
                            allocated,
                            roundRobinRank + 1,
                            allocated ? 1.0 : 0.0,
                            allocated
                                    ? "round-robin slot selected"
                                    : "waiting for next round-robin slot"
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

    private void validateResources(int availableResources) {
        if (availableResources < 0) {
            throw new IllegalArgumentException("availableResources must be non-negative");
        }
    }
}