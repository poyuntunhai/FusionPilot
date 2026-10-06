package com.fusionpilot.backend.account;

import com.fusionpilot.backend.api.ApiResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/admin")
public class AdminController {

    private final UserRepository userRepository;
    private final SessionRepository sessionRepository;
    private final UserService userService;

    public AdminController(
            UserRepository userRepository,
            SessionRepository sessionRepository,
            UserService userService
    ) {
        this.userRepository = userRepository;
        this.sessionRepository = sessionRepository;
        this.userService = userService;
    }

    @GetMapping("/users")
    public ApiResponse<List<AdminUserSummary>> users(
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        userService.requireAdmin(authorization);
        return ApiResponse.ok(userRepository.findAllUsers());
    }

    @PatchMapping("/users/{userId}/status")
    public ApiResponse<Void> updateStatus(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @PathVariable long userId,
            @Valid @RequestBody UpdateUserStatusRequest request
    ) {
        userService.requireAdmin(authorization);
        String status = request.status().trim().toUpperCase();
        if (!status.equals("ACTIVE") && !status.equals("INACTIVE")) {
            throw new IllegalArgumentException("status must be ACTIVE or INACTIVE");
        }
        userRepository.updateStatus(userId, status);
        if (status.equals("INACTIVE")) {
            sessionRepository.revokeAllForUser(userId);
        }
        return ApiResponse.ok(null);
    }

    @PostMapping("/users/{userId}/revoke-sessions")
    public ApiResponse<Void> revokeSessions(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @PathVariable long userId
    ) {
        userService.requireAdmin(authorization);
        sessionRepository.revokeAllForUser(userId);
        return ApiResponse.ok(null);
    }
}
