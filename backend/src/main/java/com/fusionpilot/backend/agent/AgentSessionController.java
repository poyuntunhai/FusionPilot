package com.fusionpilot.backend.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fusionpilot.backend.account.AuthenticatedUser;
import com.fusionpilot.backend.account.UserService;
import com.fusionpilot.backend.api.ApiResponse;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/v1/agent/sessions")
public class AgentSessionController {

    private final AgentSessionRepository repository;
    private final UserService userService;

    public AgentSessionController(AgentSessionRepository repository, UserService userService) {
        this.repository = repository;
        this.userService = userService;
    }

    @PostMapping
    public ApiResponse<Void> save(
            @RequestBody JsonNode snapshot,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        repository.save(user.userId(), snapshot);
        return ApiResponse.ok(null);
    }

    @PutMapping("/{traceId}")
    public ApiResponse<Void> update(
            @PathVariable String traceId,
            @RequestBody JsonNode snapshot,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        if (!traceId.equals(snapshot.path("trace_id").asText())) {
            throw new IllegalArgumentException("Trace ID does not match request path");
        }
        repository.save(user.userId(), snapshot);
        return ApiResponse.ok(null);
    }

    @GetMapping("/{traceId}")
    public ApiResponse<Map<String, Object>> find(
            @PathVariable String traceId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        Map<String, Object> snapshot = repository.find(user.userId(), traceId);
        return ApiResponse.ok(snapshot);
    }
}
