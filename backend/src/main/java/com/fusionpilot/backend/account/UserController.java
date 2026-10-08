package com.fusionpilot.backend.account;

import com.fusionpilot.backend.api.ApiResponse;
import com.fusionpilot.backend.simulation.SimulationCancellationService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public class UserController {

    private final UserService userService;
    private final CaptchaService captchaService;
    private final SimulationCancellationService cancellationService;

    public UserController(
            UserService userService,
            CaptchaService captchaService,
            SimulationCancellationService cancellationService
    ) {
        this.userService = userService;
        this.captchaService = captchaService;
        this.cancellationService = cancellationService;
    }

    @GetMapping("/captcha")
    public ApiResponse<CaptchaChallenge> captcha() {
        return ApiResponse.ok(captchaService.issue());
    }

    @PostMapping("/register")
    public ApiResponse<UserProfile> register(@Valid @RequestBody RegisterRequest request) {
        return ApiResponse.ok(userService.register(request));
    }

    @PostMapping("/login")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        return ApiResponse.ok(userService.login(request));
    }

    @GetMapping("/me")
    public ApiResponse<UserProfile> me(
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(new UserProfile(
                user.userId(),
                user.username(),
                user.email(),
                user.displayName(),
                user.role(),
                user.status()
        ));
    }

    @PostMapping("/logout")
    public ApiResponse<Void> logout(
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        cancellationService.cancel(user.userId());
        userService.logout(authorization);
        return ApiResponse.ok(null);
    }

    @PostMapping("/password-reset/request")
    public ApiResponse<PasswordResetResponse> requestPasswordReset(
            @Valid @RequestBody PasswordResetRequest request
    ) {
        return ApiResponse.ok(userService.requestPasswordReset(request));
    }

    @PostMapping("/password-reset/confirm")
    public ApiResponse<Void> resetPassword(@Valid @RequestBody ResetPasswordRequest request) {
        userService.resetPassword(request);
        return ApiResponse.ok(null);
    }
}
