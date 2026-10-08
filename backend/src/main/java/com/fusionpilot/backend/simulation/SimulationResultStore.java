package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.api.ResourceNotFoundException;
import com.fusionpilot.backend.persistence.SimulationRunRepository;
import com.fusionpilot.backend.persistence.SimulationRunSummary;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class SimulationResultStore {

    private final Map<String, SimulationResult> results = new ConcurrentHashMap<>();
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

    /**
     * Keeps the result in memory for the current process and, when a repository is wired,
     * persists it with its owner so playback and history stay possible across restarts.
     */
    public void save(SimulationResult result, Long userId) {
        results.put(result.runId(), result);
        if (repository != null) {
            repository.save(result, userId);
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
            results.remove(runId);
        }
        return removed;
    }

    public SimulationResult find(String runId) {
        SimulationResult result = results.get(runId);
        if (result != null) {
            return result;
        }
        if (repository != null) {
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
            results.remove(evictedRunId);
        }
        return evicted;
    }

    public void deleteSaved(long userId, String runId) {
        requireRepository();
        repository.deleteSaved(userId, runId);
        results.remove(runId);
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
