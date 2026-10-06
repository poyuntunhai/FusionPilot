package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.persistence.SimulationRunRepository;
import com.fusionpilot.backend.persistence.SimulationRunSummary;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
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

    public void save(SimulationResult result) {
        results.put(result.runId(), result);
        if (repository != null) {
            repository.save(result);
        }
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

    public List<SimulationRunSummary> history(int limit) {
        if (repository == null) {
            return List.of();
        }
        return repository.findRecent(limit);
    }

    private IllegalArgumentException notFound(String runId) {
        return new IllegalArgumentException(
                "Simulation result not found: " + runId
        );
    }
}