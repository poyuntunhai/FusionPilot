package com.fusionpilot.backend.notice;

import com.fusionpilot.backend.api.ApiResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/system/messages")
public class SystemMessageController {

    private final SystemMessageService systemMessageService;

    public SystemMessageController(SystemMessageService systemMessageService) {
        this.systemMessageService = systemMessageService;
    }

    /** Public: the bell has to work before login, so the token here is optional. */
    @GetMapping
    public ApiResponse<List<SystemMessage>> messages(
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        return ApiResponse.ok(systemMessageService.publishedMessages(authorization));
    }

    /** Needs a login because the receipt is stored per user. */
    @PostMapping("/{messageId}/read")
    public ApiResponse<Void> markRead(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @PathVariable long messageId
    ) {
        systemMessageService.markRead(authorization, messageId);
        return ApiResponse.ok(null);
    }

    /** Admin only. Returns the new id so the caller can reference the row. */
    @PostMapping
    public ApiResponse<Long> publish(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @Valid @RequestBody PublishSystemMessageRequest request
    ) {
        return ApiResponse.ok(systemMessageService.publish(authorization, request));
    }
}
