package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.api.ResourceNotFoundException;
import com.fusionpilot.backend.persistence.SimulationRunRepository;
import com.fusionpilot.backend.persistence.SimulationRunSummary;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Keeps recently produced results in memory and, when a repository is wired, persists them with
 * their owner so playback and history stay possible across restarts.
 *
 * <p>The in-memory map is a <em>cache</em>, not the source of truth. Every stored result is also
 * written to the database and {@link #find} reads it back from there when the cache misses, which is
 * what makes bounding the cache safe: dropping an entry costs a query, never data.
 *
 * <p>Bounding is the point. This map used to be an unbounded {@code ConcurrentHashMap}, and a
 * measurement showed why that is fatal on a 512 MB heap: one 50-target × 1000-step result is ~150 MB
 * live, and the per-user retention limit is 30 results. Two large runs filled the heap and the
 * process died with {@code OutOfMemoryError} while still holding the port.
 *
 * <p>{@code LinkedHashMap} in access order gives LRU behaviour. Because {@code get} reorders the
 * entries it is a structural change, so every access is synchronised; the store is touched once per
 * simulation run and once per result read, so contention is not a concern — and database reads are
 * deliberately kept outside the lock.
 */
@Service
public class SimulationResultStore {

    /**
     * Measured live cost per (target × step) unit, rounded up.
     *
     * <p>Three points were measured with {@code jcmd GC.run} + {@code GC.heap_info} against a JVM
     * started with the production heap flags: 2.4 MB for 300 units, 30.5 MB for 10,000 and 148 MB for
     * 50,000 — i.e. 8.3 KB, 3.2 KB and 3.1 KB per unit. The small configuration is dominated by
     * per-step and per-list overhead, so a single rate cannot fit all three; this one over-estimates
     * the large configurations, which are the ones that can kill the process.
     */
    private static final long BYTES_PER_TARGET_STEP = 4_096L;

    /** Floor per result: run id, config, aggregate metrics and the object graph holding them. */
    private static final long BYTES_PER_RESULT = 512L * 1024;

    /**
     * Ceiling for the whole in-memory cache.
     *
     * <p>The JVM runs with {@code -Xmx512m} and a measured idle heap of roughly 20 MB. 192 MB leaves
     * well over 250 MB for the request being served and for a result under construction — a run needs
     * its entire result in memory before it can be stored, so the peak is roughly twice one result.
     */
    static final long CACHE_BUDGET_BYTES = 192L * 1024 * 1024;

    private final Map<String, CacheEntry> results = new LinkedHashMap<>(16, 0.75f, true);
    private long cachedBytes;
    private final SimulationRunRepository repository;

    public SimulationResultStore() {
        this.repository = null;
    }

    @Autowired
    public SimulationResultStore(
            ObjectProvider<SimulationRunRepository> repositoryProvider
    ) {
        this.repository = repositoryProvider.getIfAvailable();
    }

    private static final class CacheEntry {
        private final SimulationResult result;
        private final long bytes;

        private CacheEntry(SimulationResult result, long bytes) {
            this.result = result;
            this.bytes = bytes;
        }
    }

    /**
     * Estimated live size of one result. Deliberately an estimate over the configuration rather than
     * a real object-graph traversal: it runs on every save, and {@link #BYTES_PER_TARGET_STEP} is
     * calibrated from measurements so the error is in the safe direction.
     */
    static long estimatedBytes(SimulationResult result) {
        ExperimentConfig config = result.config();
        return BYTES_PER_RESULT + BYTES_PER_TARGET_STEP
                * ExperimentConfig.scaleOf(config.targetCount(), config.simulationSteps());
    }

    public void save(SimulationResult result, Long userId) {
        if (repository != null) {
            repository.save(result, userId);
        }
        long bytes = estimatedBytes(result);
        if (bytes > CACHE_BUDGET_BYTES) {
            // Caching this would evict everything else and still not fit. It is in the database, so
            // reads fall back to the repository instead of failing.
            return;
        }
        synchronized (results) {
            CacheEntry previous = results.put(result.runId(), new CacheEntry(result, bytes));
            cachedBytes += bytes - (previous == null ? 0 : previous.bytes);
            trimToBudget();
        }
    }

    /** Called with {@code results} held. Iteration order is least-recently-used first. */
    private void trimToBudget() {
        Iterator<Map.Entry<String, CacheEntry>> iterator = results.entrySet().iterator();
        while (cachedBytes > CACHE_BUDGET_BYTES && iterator.hasNext()) {
            Map.Entry<String, CacheEntry> eldest = iterator.next();
            iterator.remove();
            cachedBytes -= eldest.getValue().bytes;
        }
    }

    private void dropFromCache(String runId) {
        synchronized (results) {
            CacheEntry removed = results.remove(runId);
            if (removed != null) {
                cachedBytes -= removed.bytes;
            }
        }
    }

    /** Observability for tests and for a future metrics endpoint. */
    public int cachedCount() {
        synchronized (results) {
            return results.size();
        }
    }

    /** Current estimated size of the cache in bytes; never above {@link #CACHE_BUDGET_BYTES}. */
    public long cachedBytes() {
        synchronized (results) {
            return cachedBytes;
        }
    }

    /**
     * Drops this user's oldest unsaved runs once more than {@code keep} exist. Unsaved runs only
     * exist to make replay work; they are not part of anyone's history, so bounding them keeps
     * the table from growing without bound.
     *
     * @return the run ids that were removed
     */
    public List<String> pruneUnsavedRuns(long userId, int keep) {
        if (repository == null) {
            return List.of();
        }
        List<String> removed = repository.pruneUnsavedRuns(userId, keep);
        for (String runId : removed) {
            dropFromCache(runId);
        }
        return removed;
    }

    public SimulationResult find(String runId) {
        CacheEntry cached;
        synchronized (results) {
            cached = results.get(runId);
        }
        if (cached != null) {
            return cached.result;
        }
        if (repository != null) {
            // Outside the lock on purpose: this is a database round trip, and holding the monitor
            // through it would serialise unrelated readers.
            return repository.find(runId)
                    .orElseThrow(() -> notFound(runId));
        }
        throw notFound(runId);
    }

    public Optional<Long> ownerOf(String runId) {
        if (repository == null) {
            return Optional.empty();
        }
        return repository.ownerOf(runId);
    }

    /** The runs this user explicitly saved, newest save first, capped by the caller. */
    public List<SimulationRunSummary> savedHistory(long userId, int limit) {
        if (repository == null) {
            return List.of();
        }
        return repository.findSavedByUser(userId, limit);
    }

    public int savedCount(long userId) {
        return repository == null ? 0 : repository.countSavedByUser(userId);
    }

    /** @return run ids evicted because the user exceeded {@code maxSaved} */
    public List<String> markSaved(long userId, String runId, int maxSaved) {
        requireRepository();
        List<String> evicted = repository.markSaved(userId, runId, maxSaved, Instant.now());
        // Evicted runs were deleted from the database, so drop the in-memory copies too.
        for (String evictedRunId : evicted) {
            dropFromCache(evictedRunId);
        }
        return evicted;
    }

    public void deleteSaved(long userId, String runId) {
        requireRepository();
        repository.deleteSaved(userId, runId);
        dropFromCache(runId);
    }

    private void requireRepository() {
        if (repository == null) {
            throw new IllegalStateException("Simulation history repository is unavailable");
        }
    }

    private ResourceNotFoundException notFound(String runId) {
        return new ResourceNotFoundException(
                "Simulation result not found: " + runId
        );
    }
}
