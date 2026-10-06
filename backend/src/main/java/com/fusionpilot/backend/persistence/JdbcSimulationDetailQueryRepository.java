package com.fusionpilot.backend.persistence;

import com.fusionpilot.backend.simulation.SimulationRunDetail;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcSimulationDetailQueryRepository {

    private final JdbcTemplate jdbcTemplate;

    public JdbcSimulationDetailQueryRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public SimulationRunDetail findDetail(String runId) {
        if (!exists(runId)) {
            throw new IllegalArgumentException(
                    "Simulation result not found: " + runId
            );
        }
        return new SimulationRunDetail(
                runId,
                truth(runId),
                observations(runId),
                fusedStates(runId),
                assignments(runId),
                metrics(runId)
        );
    }

    private boolean exists(String runId) {
        Integer count = jdbcTemplate.queryForObject(
                "select count(*) from fp_simulation_run where run_id = ?",
                Integer.class,
                runId
        );
        return count != null && count > 0;
    }

    private java.util.List<SimulationRunDetail.TruthPoint> truth(String runId) {
        return jdbcTemplate.query(
                """
                select s.time_step, t.target_id, t.x, t.y,
                       t.velocity_x, t.velocity_y
                from fp_target_truth t
                join fp_simulation_step s on s.step_id = t.step_id
                where s.run_id = ?
                order by s.time_step, t.target_id
                """,
                (rs, rowNum) -> new SimulationRunDetail.TruthPoint(
                        rs.getInt("time_step"),
                        rs.getInt("target_id"),
                        rs.getDouble("x"),
                        rs.getDouble("y"),
                        rs.getDouble("velocity_x"),
                        rs.getDouble("velocity_y")
                ),
                runId
        );
    }

    private java.util.List<SimulationRunDetail.ObservationPoint> observations(
            String runId
    ) {
        return jdbcTemplate.query(
                """
                select s.time_step, o.target_id, o.source_type, o.available,
                       o.x, o.y, o.confidence
                from fp_observation o
                join fp_simulation_step s on s.step_id = o.step_id
                where s.run_id = ?
                order by s.time_step, o.target_id, o.source_type
                """,
                (rs, rowNum) -> new SimulationRunDetail.ObservationPoint(
                        rs.getInt("time_step"),
                        rs.getInt("target_id"),
                        rs.getString("source_type"),
                        rs.getBoolean("available"),
                        rs.getDouble("x"),
                        rs.getDouble("y"),
                        rs.getDouble("confidence")
                ),
                runId
        );
    }

    private java.util.List<SimulationRunDetail.FusedStatePoint> fusedStates(
            String runId
    ) {
        return jdbcTemplate.query(
                """
                select s.time_step, f.target_id, f.x, f.y,
                       f.velocity_x, f.velocity_y, f.uncertainty,
                       f.association_confidence, f.predicted_only
                from fp_fused_state f
                join fp_simulation_step s on s.step_id = f.step_id
                where s.run_id = ?
                order by s.time_step, f.target_id
                """,
                (rs, rowNum) -> new SimulationRunDetail.FusedStatePoint(
                        rs.getInt("time_step"),
                        rs.getInt("target_id"),
                        rs.getDouble("x"),
                        rs.getDouble("y"),
                        rs.getDouble("velocity_x"),
                        rs.getDouble("velocity_y"),
                        rs.getDouble("uncertainty"),
                        rs.getDouble("association_confidence"),
                        rs.getBoolean("predicted_only")
                ),
                runId
        );
    }

    private java.util.List<SimulationRunDetail.ResourceAssignmentPoint> assignments(
            String runId
    ) {
        return jdbcTemplate.query(
                """
                select s.time_step, a.target_id, a.allocated,
                       a.priority_rank, a.priority_score, a.reason
                from fp_resource_assignment a
                join fp_simulation_step s on s.step_id = a.step_id
                where s.run_id = ?
                order by s.time_step, a.priority_rank, a.target_id
                """,
                (rs, rowNum) -> new SimulationRunDetail.ResourceAssignmentPoint(
                        rs.getInt("time_step"),
                        rs.getInt("target_id"),
                        rs.getBoolean("allocated"),
                        rs.getInt("priority_rank"),
                        rs.getDouble("priority_score"),
                        rs.getString("reason")
                ),
                runId
        );
    }

    private java.util.List<SimulationRunDetail.MetricPoint> metrics(String runId) {
        return jdbcTemplate.query(
                """
                select s.time_step, m.average_position_error, m.tracking_rate,
                       m.resource_utilization, m.allocated_target_count,
                       m.unserved_target_count
                from fp_step_metric m
                join fp_simulation_step s on s.step_id = m.step_id
                where s.run_id = ?
                order by s.time_step
                """,
                (rs, rowNum) -> new SimulationRunDetail.MetricPoint(
                        rs.getInt("time_step"),
                        rs.getDouble("average_position_error"),
                        rs.getDouble("tracking_rate"),
                        rs.getDouble("resource_utilization"),
                        rs.getInt("allocated_target_count"),
                        rs.getInt("unserved_target_count")
                ),
                runId
        );
    }
}