package com.fusionpilot.backend.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fusionpilot.backend.account.AuthenticatedUser;
import com.fusionpilot.backend.account.UserService;
import com.fusionpilot.backend.api.ApiResponse;
import com.fusionpilot.backend.api.ResourceNotFoundException;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Durable storage for multi-turn agent conversations.
 *
 * Separate from {@link AgentSessionController}, which serves the earlier single-shot agent flow.
 * The two shapes share a table but not a format, so keeping the endpoints apart means neither can
 * be written in the other's format by accident.
 */
@RestController
@RequestMapping("/api/v1/agent/conversations")
public class AgentConversationController {

    private final AgentConversationRepository repository;
    private final UserService userService;

    public AgentConversationController(AgentConversationRepository repository, UserService userService) {
        this.repository = repository;
        this.userService = userService;
    }

    @PostMapping
    public ApiResponse<Void> save(
            @RequestBody JsonNode snapshot,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        String sessionId = snapshot.path("session_id").asText("");
        if (sessionId.isBlank()) {
            throw new IllegalArgumentException("Conversation snapshot has no session_id");
        }
        repository.save(user.userId(), snapshot);
        return ApiResponse.ok(null);
    }

    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestParam(value = "limit", defaultValue = "30") int limit,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(repository.list(user.userId(), limit));
    }

    @GetMapping("/{sessionId}")
    public ApiResponse<Map<String, Object>> find(
            @PathVariable String sessionId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        Map<String, Object> snapshot = repository.find(user.userId(), sessionId);
        if (snapshot == null) {
            // Either the conversation does not exist, or it belongs to someone else. Both answer
            // the same way so a session id cannot be probed for existence.
            throw new ResourceNotFoundException("Agent conversation not found: " + sessionId);
        }
        return ApiResponse.ok(snapshot);
    }

    @DeleteMapping("/{sessionId}")
    public ApiResponse<Map<String, Object>> delete(
            @PathVariable String sessionId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        int deleted = repository.delete(user.userId(), sessionId);
        return ApiResponse.ok(Map.of("sessionId", sessionId, "deleted", deleted));
    }
}
