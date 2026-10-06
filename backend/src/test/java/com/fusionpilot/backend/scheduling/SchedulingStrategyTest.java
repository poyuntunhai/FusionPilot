package com.fusionpilot.backend.scheduling;

import com.fusionpilot.backend.fusion.FusedTargetState;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SchedulingStrategyTest {

    private final List<FusedTargetState> targets = List.of(
            new FusedTargetState(1, 0.0, 0.0, 1.0, 0.0, 1.0, 0.9, 0, false),
            new FusedTargetState(2, 0.0, 0.0, 1.0, 0.0, 8.0, 0.2, 0, true),
            new FusedTargetState(3, 0.0, 0.0, 1.0, 0.0, 2.0, 0.8, 0, false)
    );

    @Test
    void roundRobinShouldRotateTargetsAcrossTimeSteps() {
        RoundRobinSchedulingStrategy strategy = new RoundRobinSchedulingStrategy();

        SchedulingResult first = strategy.schedule(targets, 1, 0);
        SchedulingResult second = strategy.schedule(targets, 1, 1);

        assertThat(first.allocatedTargetIds()).containsExactly(1);
        assertThat(second.allocatedTargetIds()).containsExactly(2);
        assertThat(first.unservedTargetIds()).containsExactly(2, 3);
    }

    @Test
    void priorityShouldSelectUncertainPredictedTargetFirst() {
        PrioritySchedulingStrategy strategy = new PrioritySchedulingStrategy();

        SchedulingResult result = strategy.schedule(targets, 1, 0);

        assertThat(result.allocatedTargetIds()).containsExactly(2);
        assertThat(result.assignments().get(0).reason()).contains("uncertainty=");
        assertThat(result.assignments().get(0).priorityScore()).isGreaterThan(0.0);
    }

    @Test
    void strategiesShouldRespectResourceLimit() {
        PrioritySchedulingStrategy strategy = new PrioritySchedulingStrategy();

        SchedulingResult result = strategy.schedule(targets, 2, 0);

        assertThat(result.allocatedTargetIds()).hasSize(2);
        assertThat(result.assignments()).hasSize(3);
    }
}