package com.fusionpilot.backend.dataset;

import com.fusionpilot.backend.dataset.DatasetTruthSource.DatasetTruth;
import com.fusionpilot.backend.observation.TargetState;
import org.junit.jupiter.api.Test;

import java.io.BufferedReader;
import java.io.StringReader;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * The dataset→simulation bridge, tested where the arithmetic is.
 *
 * <p>Two things here are easy to get subtly wrong and impossible to notice from a green
 * end-to-end run: the velocity reconstruction (truth.csv has positions only, and the fusion
 * strategies want velocities) and the mismatch refusals (a dataset that cannot serve a
 * configuration must say why before the run starts, not die inside the loop).
 */
class DatasetTruthSourceTest {

    private static DatasetTruth parse(String csv) throws Exception {
        return DatasetTruthSource.parseTruth(new BufferedReader(new StringReader(csv)));
    }

    private static final String THREE_STEPS =
            """
            time_step,target_id,x,y
            0,1,0,0
            1,1,10,0
            2,1,20,0
            """;

    @Test
    void readsTargetsAndSteps() throws Exception {
        DatasetTruth truth = parse(THREE_STEPS);

        assertThat(truth.targetCount()).isEqualTo(1);
        assertThat(truth.stepCount()).isEqualTo(3);
        assertThat(truth.statesAt(1, 1.0).get(0).x()).isEqualTo(10.0);
    }

    @Test
    void reconstructsVelocityByDifferencing() throws Exception {
        DatasetTruth truth = parse(THREE_STEPS);

        // Interior step: central difference over two steps spanning 20 units at 1 s/step → 10 u/s.
        assertThat(truth.statesAt(1, 1.0).get(0).velocityX()).isEqualTo(10.0);
        // First step: one-sided, (10 - 0) / 1 s.
        assertThat(truth.statesAt(0, 1.0).get(0).velocityX()).isEqualTo(10.0);
        // Last step: one-sided the other way, (20 - 10) / 1 s.
        assertThat(truth.statesAt(2, 1.0).get(0).velocityX()).isEqualTo(10.0);
    }

    @Test
    void velocityScalesWithTheConfiguredStepDuration() throws Exception {
        // The same dataset run at 2 s per step must report half the speed, not the same speed:
        // velocity is derived, so it has to follow the configuration it is run under.
        DatasetTruth truth = parse(THREE_STEPS);

        assertThat(truth.statesAt(1, 2.0).get(0).velocityX()).isEqualTo(5.0);
    }

    @Test
    void aSingleStepHasNoVelocityToReconstruct() throws Exception {
        DatasetTruth truth = parse(
                """
                time_step,target_id,x,y
                0,1,42,7
                """);

        assertThat(truth.stepCount()).isEqualTo(1);
        assertThat(truth.statesAt(0, 1.0).get(0).velocityX()).isZero();
        assertThat(truth.statesAt(0, 1.0).get(0).x()).isEqualTo(42.0);
    }

    @Test
    void columnOrderIsLookedUpNotAssumed() throws Exception {
        // Import validated that the columns are present, not that they come in a fixed order.
        DatasetTruth truth = parse(
                """
                x,y,target_id,time_step
                5,6,1,0
                7,8,1,1
                """);

        assertThat(truth.statesAt(0, 1.0).get(0).x()).isEqualTo(5.0);
        assertThat(truth.statesAt(1, 1.0).get(0).y()).isEqualTo(8.0);
    }

    @Test
    void targetsAreKeptSeparateAndOrdered() throws Exception {
        DatasetTruth truth = parse(
                """
                time_step,target_id,x,y
                0,2,200,0
                0,1,100,0
                1,1,110,0
                1,2,210,0
                """);

        assertThat(truth.targetCount()).isEqualTo(2);
        // Ordered by id, so "target index 0" means the same thing every run.
        assertThat(truth.targetIds()).containsExactly(1, 2);
        assertThat(truth.statesAt(0, 1.0).get(0).x()).isEqualTo(100.0);
        assertThat(truth.statesAt(0, 1.0).get(1).x()).isEqualTo(200.0);
    }

    @Test
    void aGapIsFilledFromTheLastKnownPosition() throws Exception {
        DatasetTruth truth = parse(
                """
                time_step,target_id,x,y
                0,1,10,10
                2,1,30,30
                """);

        // Step 1 is absent from the file; carrying the previous position keeps the target count
        // and the ordering stable rather than silently renumbering what "target 1" means.
        assertThat(truth.stepCount()).isEqualTo(3);
        assertThat(truth.statesAt(1, 1.0).get(0).x()).isEqualTo(10.0);
    }

    @Test
    void aMissingRequiredColumnIsRefusedWithItsName() {
        assertThatThrownBy(() -> parse(
                """
                time_step,target_id,x
                0,1,5
                """))
                .isInstanceOf(DatasetNotUsableException.class)
                .hasMessageContaining("y");
    }

    // ------------------------------------------------------------------ the mismatch refusals

    @Test
    void aTargetCountMismatchSaysBothNumbers() throws Exception {
        DatasetTruth truth = parse(THREE_STEPS);

        assertThatThrownBy(() -> truth.validateFor(3, 10))
                .isInstanceOf(DatasetNotUsableException.class)
                .hasMessageContaining("1")
                .hasMessageContaining("3");
    }

    @Test
    void aRunLongerThanTheDatasetIsRefused() throws Exception {
        DatasetTruth truth = parse(THREE_STEPS);

        assertThatThrownBy(() -> truth.validateFor(1, 50))
                .isInstanceOf(DatasetNotUsableException.class)
                .hasMessageContaining("50");
    }

    @Test
    void aConfigurationTheDatasetCanServeIsAccepted() throws Exception {
        DatasetTruth truth = parse(THREE_STEPS);

        truth.validateFor(1, 3);
        truth.validateFor(1, 2);
    }

    @Test
    void theStateListCarriesTheDatasetsTargetIds() throws Exception {
        DatasetTruth truth = parse(
                """
                time_step,target_id,x,y
                0,7,1,1
                1,7,2,2
                """);

        List<TargetState> states = truth.statesAt(0, 1.0);

        assertThat(states).hasSize(1);
        assertThat(states.get(0).targetId()).isEqualTo(7);
        assertThat(states.get(0).timeStep()).isZero();
    }
}
