package com.fusionpilot.backend.scenario;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The per-field maxima on {@code targetCount} and {@code simulationSteps} were never a bound on the
 * thing that consumes memory — their product is. 50 × 10,000 was accepted, and a measurement puts that
 * at roughly 1.5 GB of live objects against a 512 MB heap.
 *
 * <p>It also pins that the constraint on a derived method is actually evaluated: the rule lives on
 * {@code isScaleWithinBudget()} rather than on a record component, and a constraint that silently is
 * not applied would look identical to a passing test.
 */
class ExperimentConfigScaleTest {

    private final Validator validator = Validation.buildDefaultValidatorFactory().getValidator();

    @Test
    void aConfigurationThatCannotFitInTheHeapIsRejected() {
        assertThat(violations(50, 10_000)).isNotEmpty();
    }

    @Test
    void aConfigurationJustOverTheLimitIsRejected() {
        // 50 × 1001 = 50,050 — one step past the ceiling, so the boundary is inclusive and tested on
        // both sides rather than only at a wildly invalid value.
        assertThat(violations(50, 1_001)).isNotEmpty();
    }

    @Test
    void theLargestConfigurationThatFitsIsAccepted() {
        assertThat(violations(50, 1_000)).isEmpty();
        assertThat(violations(3, 100)).isEmpty();
    }

    @Test
    void theConstraintIsEvaluatedAtAll() {
        // Guards the guard: if Bean Validation stopped looking at isScaleWithinBudget() the two
        // assertions above would still pass on the *other* constraints, so check the message.
        assertThat(violations(50, 10_000))
                .anyMatch(violation -> violation.getMessage().contains("规模过大"));
    }

    @Test
    void theValidationPropertyDoesNotLeakIntoJson() throws Exception {
        // Jackson serialises a record from its components AND from any isX()/getX() method, so the
        // constraint method above turned up as an extra "scaleWithinBudget" field in every config the
        // API returned. It is not a component, so a client echoing that config back would be sending
        // a field the record cannot accept.
        ObjectMapper mapper = new ObjectMapper();
        String json = mapper.writeValueAsString(config(3, 100));

        assertThat(json).doesNotContain("scaleWithinBudget");
    }

    @Test
    void aConfigSurvivesASerialisationRoundTrip() throws Exception {
        // The frontend posts the config back when it re-runs or saves a run, so anything Jackson adds
        // that the record cannot consume breaks that round trip.
        ExperimentConfig original = config(3, 100);
        ObjectMapper mapper = new ObjectMapper();

        String json = mapper.writeValueAsString(original);

        assertThat(mapper.readValue(json, ExperimentConfig.class)).isEqualTo(original);
    }

    private Set<jakarta.validation.ConstraintViolation<ExperimentConfig>> violations(
            int targetCount,
            int simulationSteps
    ) {
        return validator.validate(config(targetCount, simulationSteps));
    }

    static ExperimentConfig config(int targetCount, int simulationSteps) {
        return new ExperimentConfig(
                "scale-test",
                targetCount,
                simulationSteps,
                1.0,
                2,
                FusionMethod.WEIGHTED_AVERAGE,
                SchedulingPolicy.ROUND_ROBIN,
                20260928L,
                List.of(new ObservationSourceConfig(ObservationSourceType.RADAR, 3.0, 0.05, 0, 0.9))
        );
    }
}
