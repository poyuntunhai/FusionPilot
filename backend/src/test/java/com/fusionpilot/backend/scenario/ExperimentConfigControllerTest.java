package com.fusionpilot.backend.scenario;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(ExperimentConfigController.class)
@Import(ExperimentConfigService.class)
class ExperimentConfigControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void defaultConfigReturnsThreeObservationSources() throws Exception {
        mockMvc.perform(get("/api/v1/experiments/default"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.targetCount").value(3))
                .andExpect(jsonPath("$.data.observationSources.length()").value(3));
    }

    @Test
    void invalidConfigReturnsStructuredValidationError() throws Exception {
        String request = """
                {
                  "scenarioName": "",
                  "targetCount": 0,
                  "simulationSteps": 0,
                  "timeStepSeconds": 0,
                  "availableResources": 0,
                  "fusionMethod": null,
                  "schedulingPolicy": null,
                  "randomSeed": 1,
                  "observationSources": []
                }
                """;

        mockMvc.perform(post("/api/v1/experiments/validate")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(request))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.details.length()").value(org.hamcrest.Matchers.greaterThan(0)));
    }
}