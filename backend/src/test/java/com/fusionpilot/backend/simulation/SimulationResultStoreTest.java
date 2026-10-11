package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.api.ResourceNotFoundException;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.FusionMethod;
import com.fusionpilot.backend.scenario.ObservationSourceConfig;
import com.fusionpilot.backend.scenario.ObservationSourceType;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * The in-memory result cache used to be unbounded, and that is not a theoretical problem: with
 * {@code -Xmx512m}, two 50-target × 1000-step results are enough to exhaust the heap, and the process
 * was observed dying with {@code OutOfMemoryError} while still holding its port. These tests pin the
 * bound, the eviction order, and the two cases that used to be silently fatal.
 *
 * <p>No repository is wired here on purpose. The store falls back to the database on a miss, so in
 * production an evicted entry is still readable — which is exactly why bounding the cache is safe.
 * Without a repository a miss throws, and that is the signal these tests use to prove an entry really
 * left the cache.
 *
 * <p>The estimate depends only on the configuration (never on the step list), so results here carry
 * an empty step list. Their accuracy was established by measurement, not by these tests.
 */
class SimulationResultStoreTest {

    /**
     * 14 × 1000 = 14,000 units → each entry is 512 KB + 4096 × 14,000 ≈ 55 MiB, so exactly three fit
     * inside the 192 MiB budget and the fourth forces one eviction. The values are chosen against
     * the budget on purpose: the first version of this test used 12,000 units and four entries fit
     * (4 × 49.7 MB < 192 MiB), so nothing was ever evicted and the test asserted nothing.
     */
    private static final int BIG_TARGETS = 14;
    private static final int BIG_STEPS = 1_000;

    @Test
    void theEstimateGrowsWithTheConfiguration() {
        long small = SimulationResultStore.estimatedBytes(result("small", 3, 100));
        long large = SimulationResultStore.estimatedBytes(result("large", 50, 1_000));

        assertThat(small).isGreaterThan(0);
        assertThat(large).isGreaterThan(small);
        // A single max-scale run must be larger than the whole budget — that is what makes the
        // "too big to cache" path reachable rather than dead code.
        assertThat(SimulationResultStore.estimatedBytes(result("max", 50, 1_000)))
                .isGreaterThan(SimulationResultStore.CACHE_BUDGET_BYTES);
    }

    @Test
    void theCacheNeverExceedsItsBudget() {
        SimulationResultStore store = new SimulationResultStore();

        // Each default-sized entry is ~1.7 MB, so 200 of them is ~350 MB — comfortably past the
        // budget, which is the only way this test says anything.
        for (int i = 0; i < 200; i++) {
            store.save(result("run-" + i, 3, 100), 1L);
        }

        assertThat(store.cachedBytes())
                .isLessThanOrEqualTo(SimulationResultStore.CACHE_BUDGET_BYTES);
        assertThat(store.cachedCount()).isLessThan(200).isGreaterThan(0);
    }

    @Test
    void theLeastRecentlyUsedEntryLeavesFirst() {
        SimulationResultStore store = new SimulationResultStore();
        store.save(result("e1", BIG_TARGETS, BIG_STEPS), 1L);
        store.save(result("e2", BIG_TARGETS, BIG_STEPS), 1L);
        store.save(result("e3", BIG_TARGETS, BIG_STEPS), 1L);
        assertThat(store.cachedCount()).isEqualTo(3);

        // Reading e1 must protect it: eviction follows access order, not insertion order.
        store.find("e1");
        store.save(result("e4", BIG_TARGETS, BIG_STEPS), 1L);

        assertThat(store.cachedBytes())
                .isLessThanOrEqualTo(SimulationResultStore.CACHE_BUDGET_BYTES);
        // e1 was just read, so e2 is the least recently used and should be the one dropped.
        assertThat(store.find("e1").runId()).isEqualTo("e1");
        assertThat(store.find("e4").runId()).isEqualTo("e4");
        assertThatThrownBy(() -> store.find("e2")).isInstanceOf(ResourceNotFoundException.class);
    }

    @Test
    void aResultTooBigForTheWholeBudgetIsNotCachedAtAll() {
        SimulationResultStore store = new SimulationResultStore();

        // Caching this would evict everything else and still not fit, so it must be skipped rather
        // than allowed to empty the cache on every save.
        store.save(result("huge", 50, 1_000), 1L);

        assertThat(store.cachedCount()).isZero();
        assertThat(store.cachedBytes()).isZero();
    }

    @Test
    void resavingTheSameRunDoesNotDoubleCount() {
        SimulationResultStore store = new SimulationResultStore();

        store.save(result("same", 3, 100), 1L);
        long afterFirst = store.cachedBytes();
        store.save(result("same", 3, 100), 1L);

        assertThat(store.cachedCount()).isEqualTo(1);
        assertThat(store.cachedBytes()).isEqualTo(afterFirst);
    }

    private SimulationResult result(String runId, int targetCount, int simulationSteps) {
        return new SimulationResult(
                runId,
                new ExperimentConfig(
                        "test-" + runId,
                        targetCount,
                        simulationSteps,
                        1.0,
                        2,
                        FusionMethod.WEIGHTED_AVERAGE,
                        SchedulingPolicy.ROUND_ROBIN,
                        20260928L,
                        List.of(new ObservationSourceConfig(
                                ObservationSourceType.RADAR,
                                3.0,
                                0.05,
                                0,
                                0.9
                        ))
                ),
                List.of(),
                null,
                Instant.now()
        );
    }
}
