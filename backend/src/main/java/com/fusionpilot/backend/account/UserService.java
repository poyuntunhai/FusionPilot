package com.fusionpilot.backend.account;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
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
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();
    private final SecureRandom secureRandom = new SecureRandom();

    public UserService(UserRepository userRepository, SessionRepository sessionRepository) {
        this.userRepository = userRepository;
        this.sessionRepository = sessionRepository;
    }

    public UserProfile register(RegisterRequest request) {
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
