package com.fusionpilot.backend.agent;

import com.fusionpilot.backend.account.AuthenticatedUser;
import com.fusionpilot.backend.account.UserService;
import com.fusionpilot.backend.api.ApiResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Long-term per-user agent memory. One user, one note the agent keeps updating as it learns.
 */
@RestController
@RequestMapping("/api/v1/agent/memory")
public class AgentMemoryController {

    private final AgentMemoryRepository repository;
    private final UserService userService;

    public AgentMemoryController(AgentMemoryRepository repository, UserService userService) {
        this.repository = repository;
        this.userService = userService;
    }

    @GetMapping
    public ApiResponse<Map<String, Object>> get(
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        String memory = repository.get(user.userId());
        return ApiResponse.ok(Map.of("memory", memory == null ? "" : memory));
    }

    @PutMapping
    public ApiResponse<Void> save(
            @RequestBody Map<String, String> body,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        repository.save(user.userId(), body.getOrDefault("memory", ""));
        return ApiResponse.ok(null);
    }
}
