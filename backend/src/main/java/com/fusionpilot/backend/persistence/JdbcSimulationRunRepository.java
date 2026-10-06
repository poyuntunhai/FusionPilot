package com.fusionpilot.backend.persistence;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fusionpilot.backend.simulation.SimulationResult;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

@Repository
public class JdbcSimulationRunRepository implements SimulationRunRepository {

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
    public void save(SimulationResult result) {
        String configJson = writeJson(result.config());
        String resultJson = writeJson(result);
        jdbcTemplate.update("""
                insert into fp_simulation_run (
                    run_id, scenario_name, target_count, simulation_steps,
                    scheduling_policy, random_seed, average_position_error,
                    tracking_rate, resource_utilization, average_waiting_time,
                    scheduling_switches, total_steps, config_json, result_json,
                    completed_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on duplicate key update
                    scenario_name = values(scenario_name),
                    target_count = values(target_count),
                    simulation_steps = values(simulation_steps),
                    scheduling_policy = values(scheduling_policy),
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
                result.config().scenarioName(),
                result.config().targetCount(),
                result.config().simulationSteps(),
                result.config().schedulingPolicy().name(),
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
    public List<SimulationRunSummary> findRecent(int limit) {
        int boundedLimit = Math.max(1, Math.min(limit, 100));
        return jdbcTemplate.query(
                """
                select run_id, scenario_name, target_count, simulation_steps,
                       scheduling_policy, random_seed, average_position_error,
                       tracking_rate, resource_utilization, average_waiting_time,
                       scheduling_switches, total_steps, completed_at
                from fp_simulation_run
                order by completed_at desc
                limit ?
                """,
                (rs, rowNum) -> summary(rs),
                boundedLimit
        );
    }

    private SimulationRunSummary summary(ResultSet rs) throws SQLException {
        return new SimulationRunSummary(
                rs.getString("run_id"),
                rs.getString("scenario_name"),
                rs.getInt("target_count"),
                rs.getInt("simulation_steps"),
                rs.getString("scheduling_policy"),
                rs.getLong("random_seed"),
                rs.getDouble("average_position_error"),
                rs.getDouble("tracking_rate"),
                rs.getDouble("resource_utilization"),
                rs.getDouble("average_waiting_time"),
                rs.getInt("scheduling_switches"),
                rs.getInt("total_steps"),
                toInstant(rs.getTimestamp("completed_at"))
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