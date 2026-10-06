package com.fusionpilot.backend.account;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class CaptchaService {

    private static final Duration TTL = Duration.ofMinutes(5);
    private final Map<String, Challenge> challenges = new ConcurrentHashMap<>();
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
    private final SecureRandom random = new SecureRandom();

    public CaptchaChallenge issue() {
        int left = 1 + random.nextInt(9);
        int right = 1 + random.nextInt(9);
        String challengeId = UUID.randomUUID().toString();
        Instant expiresAt = Instant.now().plus(TTL);
        challenges.put(challengeId, new Challenge(encoder.encode(Integer.toString(left + right)), expiresAt));
        return new CaptchaChallenge(challengeId, left + " + " + right + " = ?", expiresAt);
    }

    public void verifyAndConsume(String challengeId, String answer) {
        if (challengeId == null || answer == null) {
            throw new InvalidCaptchaException();
        }
        Challenge challenge = challenges.remove(challengeId);
        if (challenge == null || challenge.expiresAt().isBefore(Instant.now())
                || !encoder.matches(answer.trim(), challenge.answerHash())) {
            throw new InvalidCaptchaException();
        }
    }

    private record Challenge(String answerHash, Instant expiresAt) {
    }
}
