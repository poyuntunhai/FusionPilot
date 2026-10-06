package com.fusionpilot.backend.persistence;

import com.fusionpilot.backend.fusion.FusedTargetState;
import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scheduling.ResourceAssignment;
import com.fusionpilot.backend.simulation.SimulationResult;
import com.fusionpilot.backend.simulation.SimulationStepResult;
import com.fusionpilot.backend.simulation.StepMetrics;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.List;
import java.util.Map;
import java.util.Objects;

@Repository
public class JdbcSimulationDetailRepository {

    private final JdbcTemplate jdbcTemplate;

    public JdbcSimulationDetailRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void replaceDetails(SimulationResult result) {
        jdbcTemplate.update(
                "delete from fp_simulation_step where run_id = ?",
                result.runId()
        );
        for (SimulationStepResult step : result.steps()) {
            long stepId = insertStep(result.runId(), step.timeStep());
            insertTruth(stepId, step.trueStates());
            insertObservations(stepId, step.observations());
            insertFusedStates(stepId, step.fusedStates());
            insertAssignments(stepId, step.scheduling().assignments());
            insertStepMetric(stepId, step.metrics());
        }
    }

    private long insertStep(String runId, int timeStep) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement ps = connection.prepareStatement(
                    """
                    insert into fp_simulation_step (run_id, time_step)
                    values (?, ?)
                    """,
                    Statement.RETURN_GENERATED_KEYS
            );
            ps.setString(1, runId);
            ps.setInt(2, timeStep);
            return ps;
        }, keyHolder);
        Map<String, Object> keys = keyHolder.getKeys();
        Object stepId = keys == null ? null : keys.get("step_id");
        if (stepId == null) {
            stepId = keyHolder.getKey();
        }
        return ((Number) Objects.requireNonNull(stepId)).longValue();
    }

    private void insertTruth(long stepId, List<TargetState> trueStates) {
        jdbcTemplate.batchUpdate(
                """
                insert into fp_target_truth (
                    step_id, target_id, x, y, velocity_x, velocity_y
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                trueStates,
                trueStates.size(),
                (ps, state) -> {
                    ps.setLong(1, stepId);
                    ps.setInt(2, state.targetId());
                    ps.setDouble(3, state.x());
                    ps.setDouble(4, state.y());
                    ps.setDouble(5, state.velocityX());
                    ps.setDouble(6, state.velocityY());
                }
        );
    }

    private void insertObservations(long stepId, List<Observation> observations) {
        jdbcTemplate.batchUpdate(
                """
                insert into fp_observation (
                    step_id, target_id, source_type, available, x, y, confidence
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                observations,
                observations.size(),
                (ps, observation) -> {
                    ps.setLong(1, stepId);
                    ps.setInt(2, observation.targetId());
                    ps.setString(3, observation.sourceType().name());
                    ps.setBoolean(4, observation.available());
                    ps.setDouble(5, observation.x());
                    ps.setDouble(6, observation.y());
                    ps.setDouble(7, observation.confidence());
                }
        );
    }

    private void insertFusedStates(long stepId, List<FusedTargetState> states) {
        jdbcTemplate.batchUpdate(
                """
                insert into fp_fused_state (
                    step_id, target_id, x, y, velocity_x, velocity_y,
                    uncertainty, association_confidence, predicted_only
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                states,
                states.size(),
                (ps, state) -> {
                    ps.setLong(1, stepId);
                    ps.setInt(2, state.targetId());
                    ps.setDouble(3, state.x());
                    ps.setDouble(4, state.y());
                    ps.setDouble(5, state.velocityX());
                    ps.setDouble(6, state.velocityY());
                    ps.setDouble(7, state.uncertainty());
                    ps.setDouble(8, state.associationConfidence());
                    ps.setBoolean(9, state.predictedOnly());
                }
        );
    }

    private void insertAssignments(
            long stepId,
            List<ResourceAssignment> assignments
    ) {
        jdbcTemplate.batchUpdate(
                """
                insert into fp_resource_assignment (
                    step_id, target_id, allocated, priority_rank,
                    priority_score, reason
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                assignments,
                assignments.size(),
                (ps, assignment) -> {
                    ps.setLong(1, stepId);
                    ps.setInt(2, assignment.targetId());
                    ps.setBoolean(3, assignment.allocated());
                    ps.setInt(4, assignment.rank());
                    ps.setDouble(5, assignment.priorityScore());
                    ps.setString(6, assignment.reason());
                }
        );
    }

    private void insertStepMetric(long stepId, StepMetrics metrics) {
        jdbcTemplate.update(
                """
                insert into fp_step_metric (
                    step_id, average_position_error, tracking_rate,
                    resource_utilization, allocated_target_count,
                    unserved_target_count
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                stepId,
                metrics.averagePositionError(),
                metrics.trackingRate(),
                metrics.resourceUtilization(),
                metrics.allocatedTargetCount(),
                metrics.unservedTargetCount()
        );
    }
}
