package com.fusionpilot.backend.notice;

import com.fusionpilot.backend.account.AuthenticatedUser;
import com.fusionpilot.backend.account.UserService;
import com.fusionpilot.backend.api.ResourceNotFoundException;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Locale;

@Service
public class SystemMessageService {

    private static final String DEFAULT_LEVEL = "INFO";

    private final SystemMessageRepository systemMessageRepository;
    private final UserService userService;

    public SystemMessageService(
            SystemMessageRepository systemMessageRepository,
            UserService userService
    ) {
        this.systemMessageRepository = systemMessageRepository;
        this.userService = userService;
    }

    /**
     * Readable without logging in: the notice board is how a release is announced, so it has to be
     * visible on the landing page too. A valid bearer token only upgrades the response by filling
     * in the per-user read flags.
     */
    public List<SystemMessage> publishedMessages(String authorization) {
        AuthenticatedUser viewer = userService.optionalUser(authorization);
        return systemMessageRepository.findPublished(viewer == null ? null : viewer.userId());
    }

    public void markRead(String authorization, long messageId) {
        AuthenticatedUser viewer = userService.authenticateBearer(authorization);
        if (!systemMessageRepository.existsPublished(messageId)) {
            throw new ResourceNotFoundException("System message " + messageId + " does not exist");
        }
        systemMessageRepository.markRead(messageId, viewer.userId());
    }

    public long publish(String authorization, PublishSystemMessageRequest request) {
        userService.requireAdmin(authorization);
        return systemMessageRepository.insert(
                request.title().trim(),
                request.body().trim(),
                blankToNull(request.version()),
                normalizeLevel(request.level())
        );
    }

    private String normalizeLevel(String raw) {
        if (raw == null || raw.isBlank()) {
            return DEFAULT_LEVEL;
        }
        return raw.trim().toUpperCase(Locale.ROOT);
    }

    private String blankToNull(String raw) {
        return raw == null || raw.isBlank() ? null : raw.trim();
    }
}
