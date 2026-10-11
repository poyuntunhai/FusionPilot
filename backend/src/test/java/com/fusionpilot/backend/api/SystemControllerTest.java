package com.fusionpilot.backend.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(SystemController.class)
class SystemControllerTest {
    @Autowired
    private MockMvc mockMvc;

    /**
     * Compared against the configured property instead of a literal so that bumping the version
     * does not require editing this test. It still fails if the controller reads the wrong key:
     * the two sides would then disagree.
     */
    @Value("${fusionpilot.version}")
    private String configuredVersion;

    @Test
    void healthReturnsUpStatus() throws Exception {
        mockMvc.perform(get("/api/v1/system/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.service").value("fusionpilot-backend"))
                .andExpect(jsonPath("$.data.status").value("UP"));
    }

    @Test
    void versionReturnsTheConfiguredVersion() throws Exception {
        mockMvc.perform(get("/api/v1/system/version"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.version").value(configuredVersion));
    }
}
