package com.fusionpilot.backend.simulation;

import java.util.List;

/**
 * Outcome of saving a run into the caller's history.
 *
 * @param savedCount     how many runs the user now has saved
 * @param evictedRunIds  runs dropped because the per-user cap was exceeded, oldest first.
 *                       Reported rather than silently discarded so the user can tell what went.
 */
public record SimulationSaveResult(
        String runId,
        boolean saved,
        int savedCount,
        int savedLimit,
        List<String> evictedRunIds
) {
}
