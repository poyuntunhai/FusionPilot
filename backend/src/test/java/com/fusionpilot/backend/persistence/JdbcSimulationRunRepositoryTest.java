package com.fusionpilot.backend.persistence;

import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ExperimentConfigService;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import com.fusionpilot.backend.simulation.SimulationResult;
import com.fusionpilot.backend.simulation.SimulationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class JdbcSimulationRunRepositoryTest {

    @Autowired
    private SimulationService simulationService;

    @Autowired
    private ExperimentConfigService configService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void shouldPersistNormalizedSimulationDetails() {
        SimulationResult result = simulationService.run(shortConfig());

        assertThat(count(
                "select count(*) from fp_simulation_step where run_id = ?",
                result.runId()
        )).isEqualTo(3);
        assertThat(count("""
                select count(*) from fp_target_truth t
                join fp_simulation_step s on s.step_id = t.step_id
                where s.run_id = ?
                """, result.runId())).isPositive();
        assertThat(count("""
                select count(*) from fp_observation o
                join fp_simulation_step s on s.step_id = o.step_id
                where s.run_id = ?
                """, result.runId())).isPositive();
        assertThat(count("""
                select count(*) from fp_fused_state f
                join fp_simulation_step s on s.step_id = f.step_id
                where s.run_id = ?
                """, result.runId())).isPositive();
        assertThat(count("""
                select count(*) from fp_resource_assignment a
                join fp_simulation_step s on s.step_id = a.step_id
                where s.run_id = ?
                """, result.runId())).isPositive();
        assertThat(count("""
                select count(*) from fp_step_metric m
                join fp_simulation_step s on s.step_id = m.step_id
                where s.run_id = ?
                """, result.runId())).isEqualTo(3);
    }

    private ExperimentConfig shortConfig() {
        ExperimentConfig config = configService.defaultConfig();
        return new ExperimentConfig(
                config.scenarioName(),
                2,
                3,
                config.timeStepSeconds(),
                1,
                config.fusionMethod(),
                SchedulingPolicy.PRIORITY,
                config.randomSeed(),
                config.observationSources()
        );
    }

    private int count(String sql, Object... args) {
        Integer count = jdbcTemplate.queryForObject(sql, Integer.class, args);
        return count == null ? 0 : count;
    }
}