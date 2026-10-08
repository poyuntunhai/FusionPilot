package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.api.ResourceNotFoundException;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import jakarta.annotation.PreDestroy;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicBoolean;

@Service
public class SimulationJobService {

    private final SimulationService simulationService;
    private final SimulationCancellationService cancellationService;
    private final ExecutorService executor = Executors.newFixedThreadPool(4);
    private final Map<String, JobState> jobs = new ConcurrentHashMap<>();

    public SimulationJobService(
            SimulationService simulationService,
            SimulationCancellationService cancellationService
    ) {
        this.simulationService = simulationService;
        this.cancellationService = cancellationService;
    }

    public SimulationJobStatus submit(long userId, ExperimentConfig config) {
        String jobId = UUID.randomUUID().toString();
        JobState state = new JobState(jobId, userId, config.simulationSteps());
        jobs.put(jobId, state);
        state.future = executor.submit(() -> execute(state, config));
        return state.snapshot();
    }

    public SimulationJobStatus status(long userId, String jobId) {
        JobState state = jobs.get(jobId);
        if (state == null || state.userId != userId) {
            throw new ResourceNotFoundException("Simulation job not found");
        }
        return state.snapshot();
    }

    public void cancel(long userId) {
        jobs.values().stream()
                .filter(state -> state.userId == userId)
                .filter(state -> "QUEUED".equals(state.status) || "RUNNING".equals(state.status))
                .forEach(state -> {
                    state.cancelled.set(true);
                    state.status = "CANCELLING";
                    state.message = "Stopping simulation...";
                    cancellationService.cancel(userId);
                });
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    private void execute(JobState state, ExperimentConfig config) {
        if (state.cancelled.get()) {
            state.status = "CANCELLED";
            state.message = "Simulation stopped";
            return;
        }
        state.status = "RUNNING";
        state.message = "Simulation is running";
        try {
            SimulationResult result = simulationService.run(
                    config,
                    state.userId,
                    state.cancelled::get,
                    completed -> state.updateProgress(completed)
            );
            if (state.cancelled.get()) {
                state.status = "CANCELLED";
                state.message = "Simulation stopped";
                return;
            }
            state.completedSteps = state.totalSteps;
            state.status = "COMPLETED";
            state.message = "Simulation completed";
            state.runId = result.runId();
            state.result = result;
        } catch (SimulationCancelledException exception) {
            state.status = "CANCELLED";
            state.message = "Simulation stopped";
        } catch (Exception exception) {
            state.status = "FAILED";
            state.message = exception.getMessage() == null
                    ? "Simulation failed"
                    : exception.getMessage();
        }
    }

    private static final class JobState {
        private final String jobId;
        private final long userId;
        private final int totalSteps;
        private final AtomicBoolean cancelled = new AtomicBoolean();
        private volatile String status = "QUEUED";
        private volatile String message = "Simulation queued";
        private volatile int completedSteps;
        private volatile String runId;
        private volatile SimulationResult result;
        private volatile Future<?> future;

        private JobState(String jobId, long userId, int totalSteps) {
            this.jobId = jobId;
            this.userId = userId;
            this.totalSteps = totalSteps;
        }

        private void updateProgress(int completed) {
            completedSteps = Math.min(totalSteps, completed);
        }

        private SimulationJobStatus snapshot() {
            int percent = totalSteps == 0
                    ? 0
                    : Math.min(100, (completedSteps * 100) / totalSteps);
            return new SimulationJobStatus(
                    jobId,
                    status,
                    percent,
                    completedSteps,
                    totalSteps,
                    message,
                    runId,
                    result
            );
        }
    }
}
