package com.fusionpilot.backend.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(SystemController.class)
class SystemControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @Test
    void healthReturnsUpStatus() throws Exception {
        mockMvc.perform(get("/api/v1/system/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.service").value("fusionpilot-backend"))
                .andExpect(jsonPath("$.data.status").value("UP"));
    }

    @Test
    void versionReturnsVersion() throws Exception {
        mockMvc.perform(get("/api/v1/system/version"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.version").value("0.1.0-SNAPSHOT"));
    }
}
