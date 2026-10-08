package com.fusionpilot.backend.persistence;

import com.fusionpilot.backend.simulation.SimulationResult;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface SimulationRunRepository {

    /** Persists a finished run and records who owns it. */
    void save(SimulationResult result, Long userId);

    Optional<SimulationResult> find(String runId);

    /** Owner of a run, or empty when the run is unknown or predates ownership tracking. */
    Optional<Long> ownerOf(String runId);

    /** Runs this user explicitly saved, newest save first. */
    List<SimulationRunSummary> findSavedByUser(long userId, int limit);

    /** How many runs this user currently has saved. */
    int countSavedByUser(long userId);

    /**
     * Marks a run as saved for its owner, then trims the owner's saved list down to
     * {@code maxSaved} entries by deleting the oldest.
     *
     * @return the run ids evicted to respect the cap, oldest first
     */
    List<String> markSaved(long userId, String runId, int maxSaved, Instant savedAt);

    /** Removes a run from its owner's saved history and deletes it. */
    void deleteSaved(long userId, String runId);

    /**
     * Deletes this user's unsaved runs beyond the newest {@code keep}. Saved runs are never
     * touched. Called after every run so the table cannot grow without bound.
     *
     * @return the run ids that were deleted
     */
    List<String> pruneUnsavedRuns(long userId, int keep);
}
