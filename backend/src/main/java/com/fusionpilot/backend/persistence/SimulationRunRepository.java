package com.fusionpilot.backend.persistence;

import com.fusionpilot.backend.simulation.SimulationResult;

import java.util.List;
import java.util.Optional;

public interface SimulationRunRepository {
    void save(SimulationResult result);

    Optional<SimulationResult> find(String runId);

    List<SimulationRunSummary> findRecent(int limit);
}