package com.fusionpilot.backend.account;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;

@Service
public class UserService {

    private final UserRepository userRepository;
    private final SessionRepository sessionRepository;
    private final PasswordResetRepository passwordResetRepository;
    private final CaptchaService captchaService;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();
    private final SecureRandom secureRandom = new SecureRandom();
    private final boolean returnDevelopmentResetToken;

    public UserService(
            UserRepository userRepository,
            SessionRepository sessionRepository,
            PasswordResetRepository passwordResetRepository,
            CaptchaService captchaService,
            @Value("${fusionpilot.auth.return-development-reset-token:false}") boolean returnDevelopmentResetToken
    ) {
        this.userRepository = userRepository;
        this.sessionRepository = sessionRepository;
        this.passwordResetRepository = passwordResetRepository;
        this.captchaService = captchaService;
        this.returnDevelopmentResetToken = returnDevelopmentResetToken;
    }

    public UserProfile register(RegisterRequest request) {
        captchaService.verifyAndConsume(request.captchaId(), request.captchaAnswer());
        String username = request.username().trim();
        String email = request.email().trim().toLowerCase();
        String displayName = request.displayName().trim();
        if (userRepository.existsByUsernameOrEmail(username, email)) {
            throw new UserAlreadyExistsException();
        }
        return userRepository.insert(
                username,
                email,
                passwordEncoder.encode(request.password()),
                displayName
        );
    }

    public LoginResponse login(LoginRequest request) {
        captchaService.verifyAndConsume(request.captchaId(), request.captchaAnswer());
        String login = request.login().trim();
        UserCredentials credentials = userRepository.findCredentials(login)
                .filter(user -> "ACTIVE".equals(user.status()))
                .orElseThrow(InvalidCredentialsException::new);
        if (!passwordEncoder.matches(request.password(), credentials.passwordHash())) {
            throw new InvalidCredentialsException();
        }
        String accessToken = newToken();
        Instant expiresAt = Instant.now().plus(Duration.ofDays(7));
        sessionRepository.insert(credentials.userId(), sha256(accessToken), expiresAt);
        userRepository.markLogin(credentials.userId());
        return new LoginResponse(accessToken, expiresAt, credentials.profile());
    }

    public PasswordResetResponse requestPasswordReset(PasswordResetRequest request) {
        captchaService.verifyAndConsume(request.captchaId(), request.captchaAnswer());
        UserCredentials credentials = userRepository.findCredentials(request.login().trim()).orElse(null);
        if (credentials == null || !"ACTIVE".equals(credentials.status())) {
            return new PasswordResetResponse(
                    "If the account exists, a password reset request has been created.",
                    null
            );
        }
        String token = newToken();
        passwordResetRepository.invalidateForUser(credentials.userId());
        passwordResetRepository.insert(
                credentials.userId(),
                sha256(token),
                Instant.now().plus(Duration.ofMinutes(15))
        );
        return new PasswordResetResponse(
                "If the account exists, a password reset request has been created.",
                returnDevelopmentResetToken ? token : null
        );
    }

    public void resetPassword(ResetPasswordRequest request) {
        PasswordResetRepository.ResetToken resetToken =
                passwordResetRepository.findValid(sha256(request.resetToken().trim()));
        if (resetToken == null) {
            throw new InvalidPasswordResetTokenException();
        }
        userRepository.updatePassword(
                resetToken.userId(),
                passwordEncoder.encode(request.newPassword())
        );
        passwordResetRepository.markUsed(resetToken.resetId());
        sessionRepository.revokeAllForUser(resetToken.userId());
    }

    public AuthenticatedUser authenticateBearer(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            throw new UnauthorizedException();
        }
        String token = authorization.substring("Bearer ".length()).trim();
        if (token.isEmpty()) {
            throw new UnauthorizedException();
        }
        AuthenticatedUser user = sessionRepository.findActiveUser(sha256(token));
        if (user == null || !"ACTIVE".equals(user.status())) {
            throw new UnauthorizedException();
        }
        return user;
    }

    public AuthenticatedUser requireAdmin(String authorization) {
        AuthenticatedUser user = authenticateBearer(authorization);
        if (!user.isAdmin()) {
            throw new ForbiddenException();
        }
        return user;
    }

    public void logout(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            return;
        }
        String token = authorization.substring("Bearer ".length()).trim();
        if (!token.isEmpty()) {
            sessionRepository.revoke(sha256(token));
        }
    }

    private String newToken() {
        byte[] bytes = new byte[32];
        secureRandom.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder();
            for (byte item : digest) {
                result.append(String.format("%02x", item));
            }
            return result.toString();
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }
}
