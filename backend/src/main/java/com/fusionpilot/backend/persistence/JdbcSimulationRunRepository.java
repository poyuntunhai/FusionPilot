package com.fusionpilot.backend.persistence;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fusionpilot.backend.api.ResourceNotFoundException;
import com.fusionpilot.backend.simulation.SimulationResult;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;

@Repository
public class JdbcSimulationRunRepository implements SimulationRunRepository {

    private static final String SUMMARY_COLUMNS = """
            run_id, scenario_name, target_count, simulation_steps,
            scheduling_policy, fusion_method, random_seed, average_position_error,
            tracking_rate, resource_utilization, average_waiting_time,
            scheduling_switches, total_steps, completed_at, saved_at
            """;

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final JdbcSimulationDetailRepository detailRepository;

    public JdbcSimulationRunRepository(
            JdbcTemplate jdbcTemplate,
            ObjectMapper objectMapper,
            JdbcSimulationDetailRepository detailRepository
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.detailRepository = detailRepository;
    }

    @Override
    @Transactional
    public void save(SimulationResult result, Long userId) {
        String configJson = writeJson(result.config());
        String resultJson = writeJson(result);
        jdbcTemplate.update("""
                insert into fp_simulation_run (
                    run_id, user_id, scenario_name, target_count, simulation_steps,
                    scheduling_policy, fusion_method, random_seed, average_position_error,
                    tracking_rate, resource_utilization, average_waiting_time,
                    scheduling_switches, total_steps, config_json, result_json,
                    completed_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on duplicate key update
                    user_id = values(user_id),
                    scenario_name = values(scenario_name),
                    target_count = values(target_count),
                    simulation_steps = values(simulation_steps),
                    scheduling_policy = values(scheduling_policy),
                    fusion_method = values(fusion_method),
                    random_seed = values(random_seed),
                    average_position_error = values(average_position_error),
                    tracking_rate = values(tracking_rate),
                    resource_utilization = values(resource_utilization),
                    average_waiting_time = values(average_waiting_time),
                    scheduling_switches = values(scheduling_switches),
                    total_steps = values(total_steps),
                    config_json = values(config_json),
                    result_json = values(result_json),
                    completed_at = values(completed_at)
                """,
                result.runId(),
                userId,
                result.config().scenarioName(),
                result.config().targetCount(),
                result.config().simulationSteps(),
                result.config().schedulingPolicy().name(),
                result.config().fusionMethod().name(),
                result.config().randomSeed(),
                result.metrics().averagePositionError(),
                result.metrics().trackingRate(),
                result.metrics().resourceUtilization(),
                result.metrics().averageWaitingTime(),
                result.metrics().schedulingSwitches(),
                result.metrics().totalSteps(),
                configJson,
                resultJson,
                Timestamp.from(result.completedAt())
        );
        detailRepository.replaceDetails(result);
    }

    @Override
    public Optional<SimulationResult> find(String runId) {
        List<SimulationResult> results = jdbcTemplate.query(
                "select result_json from fp_simulation_run where run_id = ?",
                (rs, rowNum) -> readResult(rs.getString("result_json")),
                runId
        );
        return results.stream().findFirst();
    }

    @Override
    public Optional<Long> ownerOf(String runId) {
        List<Long> owners = jdbcTemplate.query(
                "select user_id from fp_simulation_run where run_id = ?",
                (rs, rowNum) -> {
                    long value = rs.getLong("user_id");
                    return rs.wasNull() ? null : value;
                },
                runId
        );
        return owners.stream().findFirst();
    }

    @Override
    public List<SimulationRunSummary> findSavedByUser(long userId, int limit) {
        int boundedLimit = Math.max(1, Math.min(limit, 100));
        return jdbcTemplate.query(
                "select " + SUMMARY_COLUMNS + """
                from fp_simulation_run
                where user_id = ? and saved = true
                order by save_seq desc
                limit ?
                """,
                (rs, rowNum) -> summary(rs),
                userId,
                boundedLimit
        );
    }

    @Override
    public int countSavedByUser(long userId) {
        Integer count = jdbcTemplate.queryForObject(
                "select count(*) from fp_simulation_run where user_id = ? and saved = true",
                Integer.class,
                userId
        );
        return count == null ? 0 : count;
    }

    @Override
    @Transactional
    public List<String> markSaved(long userId, String runId, int maxSaved, Instant savedAt) {
        // The next save order is resolved in Java rather than with a nested UPDATE subquery.
        // Doing it in SQL reads the table being modified, which MySQL rejects outright and H2
        // resolves inconsistently; this method is transactional, so the read-then-write is safe.
        Integer currentMax = jdbcTemplate.queryForObject(
                "select max(save_seq) from fp_simulation_run where user_id = ? and saved = true",
                Integer.class,
                userId
        );
        int nextSequence = (currentMax == null ? 0 : currentMax) + 1;

        int updated = jdbcTemplate.update(
                """
                update fp_simulation_run
                set saved = true, saved_at = ?, save_seq = ?
                where run_id = ? and user_id = ?
                """,
                Timestamp.from(savedAt),
                nextSequence,
                runId,
                userId
        );
        if (updated == 0) {
            throw new ResourceNotFoundException("Simulation result not found for this user: " + runId);
        }

        // Every run stays persisted so playback works, but the saved list is capped. Anything
        // beyond the cap is deleted outright, cascading to the detail tables.
        //
        // ORDER BY must be DESC here: skipping the newest `maxSaved` rows is what leaves the
        // older overflow behind. Ascending order would skip the *oldest* rows and delete the run
        // the caller just saved.
        int boundedCap = Math.max(1, maxSaved);
        List<String> evicted = jdbcTemplate.query(
                """
                select run_id from fp_simulation_run
                where user_id = ? and saved = true
                order by save_seq desc
                limit 100 offset ?
                """,
                (rs, rowNum) -> rs.getString("run_id"),
                userId,
                boundedCap
        );
        for (String evictedRunId : evicted) {
            jdbcTemplate.update("delete from fp_simulation_run where run_id = ? and user_id = ?", evictedRunId, userId);
        }
        // The query walks newest-first, so report the removals oldest-first instead.
        List<String> oldestFirst = new ArrayList<>(evicted);
        Collections.reverse(oldestFirst);
        return oldestFirst;
    }

    @Override
    @Transactional
    public void deleteSaved(long userId, String runId) {
        jdbcTemplate.update(
                "delete from fp_simulation_run where run_id = ? and user_id = ?",
                runId,
                userId
        );
    }

    @Override
    @Transactional
    public List<String> pruneUnsavedRuns(long userId, int keep) {
        int boundedKeep = Math.max(1, keep);
        // Overflow rows are selected first and then deleted by id. A NOT IN over a subquery on
        // the same table is rejected by MySQL and resolved inconsistently by H2.
        List<String> stale = jdbcTemplate.query(
                """
                select run_id from fp_simulation_run
                where user_id = ? and saved = false
                order by completed_at desc, run_id desc
                limit 500 offset ?
                """,
                (rs, rowNum) -> rs.getString("run_id"),
                userId,
                boundedKeep
        );
        if (stale.isEmpty()) {
            return List.of();
        }
        jdbcTemplate.batchUpdate(
                "delete from fp_simulation_run where run_id = ? and user_id = ? and saved = false",
                stale.stream().map(runId -> new Object[]{runId, userId}).toList()
        );
        return stale;
    }

    private SimulationRunSummary summary(ResultSet rs) throws SQLException {
        return new SimulationRunSummary(
                rs.getString("run_id"),
                rs.getString("scenario_name"),
                rs.getInt("target_count"),
                rs.getInt("simulation_steps"),
                rs.getString("scheduling_policy"),
                rs.getString("fusion_method"),
                rs.getLong("random_seed"),
                rs.getDouble("average_position_error"),
                rs.getDouble("tracking_rate"),
                rs.getDouble("resource_utilization"),
                rs.getDouble("average_waiting_time"),
                rs.getInt("scheduling_switches"),
                rs.getInt("total_steps"),
                toInstant(rs.getTimestamp("completed_at")),
                toInstant(rs.getTimestamp("saved_at"))
        );
    }

    private Instant toInstant(Timestamp timestamp) {
        return timestamp == null ? Instant.EPOCH : timestamp.toInstant();
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exc) {
            throw new IllegalStateException("Failed to serialize simulation data", exc);
        }
    }

    private SimulationResult readResult(String json) {
        try {
            return objectMapper.readValue(json, SimulationResult.class);
        } catch (JsonProcessingException exc) {
            throw new IllegalStateException("Failed to deserialize simulation result", exc);
        }
    }
}
