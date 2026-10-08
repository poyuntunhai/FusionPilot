package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.account.ForbiddenException;
import com.fusionpilot.backend.api.ResourceNotFoundException;
import com.fusionpilot.backend.persistence.SimulationRunSummary;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ExperimentConfigService;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
class SimulationHistoryTest {

    @Autowired
    private SimulationService simulationService;

    @Autowired
    private ExperimentConfigService configService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void historyIsCappedPerUserAndEvictsTheOldestSave() {
        long userId = insertUser("hist_cap");
        List<String> runIds = new ArrayList<>();

        int saves = SimulationService.MAX_SAVED_RUNS_PER_USER + 2;
        for (int index = 0; index < saves; index++) {
            SimulationResult result = simulationService.run(shortConfig(), userId);
            runIds.add(result.runId());
            simulationService.saveToHistory(userId, result.runId());
        }

        List<String> savedIds = simulationService.savedHistory(userId, 50).stream()
                .map(SimulationRunSummary::runId)
                .toList();

        assertThat(savedIds).hasSize(SimulationService.MAX_SAVED_RUNS_PER_USER);
        assertThat(savedIds).contains(runIds.get(saves - 1));
        // The two oldest saves were evicted to stay inside the cap.
        assertThat(savedIds).doesNotContain(runIds.get(0), runIds.get(1));
    }

    @Test
    void evictionIsReportedBackToTheCaller() {
        long userId = insertUser("hist_evict");
        String firstRunId = null;
        SimulationSaveResult last = null;

        for (int index = 0; index <= SimulationService.MAX_SAVED_RUNS_PER_USER; index++) {
            SimulationResult result = simulationService.run(shortConfig(), userId);
            if (firstRunId == null) {
                firstRunId = result.runId();
            }
            last = simulationService.saveToHistory(userId, result.runId());
        }

        assertThat(last).isNotNull();
        assertThat(last.savedLimit()).isEqualTo(SimulationService.MAX_SAVED_RUNS_PER_USER);
        assertThat(last.savedCount()).isEqualTo(SimulationService.MAX_SAVED_RUNS_PER_USER);
        assertThat(last.evictedRunIds()).containsExactly(firstRunId);
    }

    @Test
    void historyNeverLeaksAnotherUsersRuns() {
        long owner = insertUser("hist_owner");
        long stranger = insertUser("hist_stranger");
        SimulationResult result = simulationService.run(shortConfig(), owner);
        simulationService.saveToHistory(owner, result.runId());

        assertThat(simulationService.savedHistory(owner, 10)).hasSize(1);
        assertThat(simulationService.savedHistory(stranger, 10)).isEmpty();
    }

    @Test
    void onlyTheOwnerMaySaveOrReadARun() {
        long owner = insertUser("hist_own2");
        long stranger = insertUser("hist_str2");
        SimulationResult result = simulationService.run(shortConfig(), owner);

        assertThatThrownBy(() -> simulationService.saveToHistory(stranger, result.runId()))
                .isInstanceOf(ForbiddenException.class);
        assertThatThrownBy(() -> simulationService.requireReadAccess(result.runId(), stranger))
                .isInstanceOf(ForbiddenException.class);
        assertThatCode(() -> simulationService.requireReadAccess(result.runId(), owner))
                .doesNotThrowAnyException();
    }

    @Test
    void unsavedRunsAreTrimmedToARecentWindow() {
        long userId = insertUser("hist_prune");
        int total = SimulationService.MAX_UNSAVED_RUNS_PER_USER + 6;
        List<String> runIds = new ArrayList<>();

        for (int index = 0; index < total; index++) {
            runIds.add(simulationService.run(shortConfig(), userId).runId());
        }

        assertThat(count(
                "select count(*) from fp_simulation_run where user_id = ? and saved = false",
                userId
        )).isEqualTo(SimulationService.MAX_UNSAVED_RUNS_PER_USER);
        // The newest run survives; the oldest overflow is gone.
        assertThat(count("select count(*) from fp_simulation_run where run_id = ?", runIds.get(total - 1)))
                .isEqualTo(1);
        assertThat(count("select count(*) from fp_simulation_run where run_id = ?", runIds.get(0)))
                .isZero();
        // Pruning cascades to the normalized detail tables.
        assertThat(count("select count(*) from fp_simulation_step where run_id = ?", runIds.get(0)))
                .isZero();
    }

    @Test
    void trimmingUnsavedRunsNeverTouchesSavedOnes() {
        long userId = insertUser("hist_prune_saved");
        SimulationResult saved = simulationService.run(shortConfig(), userId);
        simulationService.saveToHistory(userId, saved.runId());

        for (int index = 0; index < SimulationService.MAX_UNSAVED_RUNS_PER_USER + 5; index++) {
            simulationService.run(shortConfig(), userId);
        }

        assertThat(count(
                "select count(*) from fp_simulation_run where run_id = ? and saved = true",
                saved.runId()
        )).isEqualTo(1);
        assertThat(simulationService.savedHistory(userId, 10)).hasSize(1);
        assertThat(count(
                "select count(*) from fp_simulation_run where user_id = ? and saved = false",
                userId
        )).isEqualTo(SimulationService.MAX_UNSAVED_RUNS_PER_USER);
    }

    @Test
    void unknownRunReportsNotFoundRatherThanAServerError() {
        long userId = insertUser("hist_404");
        String missingRunId = "00000000-0000-0000-0000-000000000000";

        assertThatThrownBy(() -> simulationService.find(missingRunId))
                .isInstanceOf(ResourceNotFoundException.class);
        // A run nobody owns is treated as readable legacy data; the lookup is what fails.
        assertThatCode(() -> simulationService.requireReadAccess(missingRunId, userId))
                .doesNotThrowAnyException();
    }

    @Test
    void removingFromHistoryDeletesTheRunEntirely() {
        long userId = insertUser("hist_rm");
        SimulationResult result = simulationService.run(shortConfig(), userId);
        simulationService.saveToHistory(userId, result.runId());
        assertThat(simulationService.savedHistory(userId, 10)).hasSize(1);

        simulationService.removeFromHistory(userId, result.runId());

        assertThat(simulationService.savedHistory(userId, 10)).isEmpty();
        assertThat(count("select count(*) from fp_simulation_run where run_id = ?", result.runId()))
                .isZero();
        // Deleting the run must cascade to the normalized detail tables.
        assertThat(count("select count(*) from fp_simulation_step where run_id = ?", result.runId()))
                .isZero();
    }

    @Test
    void unsavedRunsStayOutOfHistoryButRemainPlayable() {
        long userId = insertUser("hist_unsaved");
        SimulationResult result = simulationService.run(shortConfig(), userId);

        assertThat(simulationService.savedHistory(userId, 10)).isEmpty();
        // Persistence still happens for every run so replay keeps working before saving.
        assertThat(count("select count(*) from fp_simulation_run where run_id = ?", result.runId()))
                .isEqualTo(1);
        assertThat(count("select count(*) from fp_simulation_step where run_id = ?", result.runId()))
                .isPositive();
    }

    private ExperimentConfig shortConfig() {
        ExperimentConfig config = configService.defaultConfig();
        return new ExperimentConfig(
                "history-check",
                2,
                3,
                config.timeStepSeconds(),
                1,
                config.fusionMethod(),
                SchedulingPolicy.ROUND_ROBIN,
                config.randomSeed(),
                config.observationSources()
        );
    }

    private long insertUser(String username) {
        jdbcTemplate.update("""
                insert into fp_user (username, email, password_hash, display_name, role, status)
                values (?, ?, ?, ?, 'USER', 'ACTIVE')
                """, username, username + "@test.local", "not-a-real-hash", username);
        Long userId = jdbcTemplate.queryForObject(
                "select user_id from fp_user where username = ?",
                Long.class,
                username
        );
        return userId == null ? -1L : userId;
    }

    private int count(String sql, Object... args) {
        Integer count = jdbcTemplate.queryForObject(sql, Integer.class, args);
        return count == null ? 0 : count;
    }
}
