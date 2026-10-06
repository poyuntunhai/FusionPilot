package com.fusionpilot.backend.scheduling;

import com.fusionpilot.backend.scenario.SchedulingPolicy;

import java.util.List;

public record SchedulingResult(
        int timeStep,
        SchedulingPolicy policy,
        int availableResources,
        List<ResourceAssignment> assignments
) {
    public List<Integer> allocatedTargetIds() {
        return assignments.stream()
                .filter(ResourceAssignment::allocated)
                .map(ResourceAssignment::targetId)
                .toList();
    }

    public List<Integer> unservedTargetIds() {
        return assignments.stream()
                .filter(assignment -> !assignment.allocated())
                .map(ResourceAssignment::targetId)
                .toList();
    }
}