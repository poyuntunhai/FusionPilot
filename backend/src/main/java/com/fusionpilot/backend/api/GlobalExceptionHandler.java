package com.fusionpilot.backend.api;

import com.fusionpilot.backend.account.UserAlreadyExistsException;
import com.fusionpilot.backend.account.InvalidCredentialsException;
import com.fusionpilot.backend.account.InvalidCaptchaException;
import com.fusionpilot.backend.account.InvalidPasswordResetTokenException;
import com.fusionpilot.backend.account.UnauthorizedException;
import com.fusionpilot.backend.account.ForbiddenException;
import com.fusionpilot.backend.simulation.SimulationCancelledException;
import com.fusionpilot.backend.dataset.DatasetImportException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.support.MissingServletRequestPartException;

import java.util.List;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(MissingServletRequestPartException.class)
    public ResponseEntity<ErrorResponse> handleMissingMultipartPart(
            MissingServletRequestPartException exception
    ) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ErrorResponse.of(
                        "DATASET_FILE_REQUIRED",
                        "A dataset file is required",
                        List.of(exception.getRequestPartName())
                ));
    }

    @ExceptionHandler(DatasetImportException.class)
    public ResponseEntity<ErrorResponse> handleDatasetImport(DatasetImportException exception) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ErrorResponse.of("DATASET_IMPORT_ERROR", exception.getMessage(), List.of()));
    }

    @ExceptionHandler(SimulationCancelledException.class)
    public ResponseEntity<ErrorResponse> handleSimulationCancelled() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(ErrorResponse.of("SIMULATION_CANCELLED", "Simulation cancelled by user", List.of()));
    }

    @ExceptionHandler(InvalidCaptchaException.class)
    public ResponseEntity<ErrorResponse> handleInvalidCaptcha() {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ErrorResponse.of("INVALID_CAPTCHA", "Captcha is invalid or expired", List.of()));
    }

    @ExceptionHandler(InvalidPasswordResetTokenException.class)
    public ResponseEntity<ErrorResponse> handleInvalidPasswordResetToken() {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ErrorResponse.of("INVALID_RESET_TOKEN", "Password reset token is invalid or expired", List.of()));
    }

    @ExceptionHandler(UnauthorizedException.class)
    public ResponseEntity<ErrorResponse> handleUnauthorized() {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(ErrorResponse.of("UNAUTHORIZED", "Authentication is required", List.of()));
    }

    @ExceptionHandler(ResourceNotFoundException.class)
    public ResponseEntity<ErrorResponse> handleResourceNotFound(ResourceNotFoundException exception) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ErrorResponse.of("NOT_FOUND", exception.getMessage(), List.of()));
    }

    @ExceptionHandler(ForbiddenException.class)
    public ResponseEntity<ErrorResponse> handleForbidden(ForbiddenException exception) {
        String message = exception.getMessage() == null || exception.getMessage().isBlank()
                ? "Administrator permission is required"
                : exception.getMessage();
        return ResponseEntity.status(HttpStatus.FORBIDDEN)
                .body(ErrorResponse.of("FORBIDDEN", message, List.of()));
    }
    @ExceptionHandler(InvalidCredentialsException.class)
    public ResponseEntity<ErrorResponse> handleInvalidCredentials() {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(ErrorResponse.of(
                        "INVALID_CREDENTIALS",
                        "Invalid username/email or password",
                        List.of()
                ));
    }

    @ExceptionHandler(UserAlreadyExistsException.class)
    public ResponseEntity<ErrorResponse> handleUserAlreadyExists() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(ErrorResponse.of(
                        "USER_ALREADY_EXISTS",
                        "Username or email is already registered",
                        List.of()
                ));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidationException(MethodArgumentNotValidException exception) {
        List<String> details = exception.getBindingResult()
                .getFieldErrors()
                .stream()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .toList();
        ErrorResponse response = ErrorResponse.of(
                "VALIDATION_ERROR",
                "Experiment configuration validation failed",
                details
        );
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(response);
    }

    /**
     * Database failures. Without this they fell through to the catch-all and the client got
     * "Unexpected server error" plus a class name in {@code details} — which is how a result too large
     * for the server's {@code max_allowed_packet} presented itself: a simulation that had already
     * finished, then a save that failed, and nothing anyone could act on.
     *
     * <p>Both drivers are declared {@code runtime} scope on purpose (the application starts against
     * either H2 or MySQL), so their exception types cannot be referenced here. Walking the cause chain
     * for a class <em>name</em> is the price of that.
     */
    @ExceptionHandler(DataAccessException.class)
    public ResponseEntity<ErrorResponse> handleDataAccess(DataAccessException exception) {
        String rootCause = rootCauseName(exception);
        if (hasCauseNamed(exception, "PacketTooBigException")) {
            return ResponseEntity.status(HttpStatus.PAYLOAD_TOO_LARGE)
                    .body(ErrorResponse.of(
                            "RESULT_TOO_LARGE",
                            "仿真结果太大，数据库拒绝写入：请减小运行规模（目标数 × 时间步数），"
                                    + "或把数据库的 max_allowed_packet 调到 32M 以上。",
                            List.of(rootCause)
                    ));
        }
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(ErrorResponse.of(
                        "DATABASE_ERROR",
                        "数据库操作失败，请稍后重试。",
                        List.of(rootCause)
                ));
    }

    private boolean hasCauseNamed(Throwable throwable, String simpleName) {
        for (Throwable current = throwable; current != null; current = current.getCause()) {
            if (simpleName.equals(current.getClass().getSimpleName())) {
                return true;
            }
        }
        return false;
    }

    private String rootCauseName(Throwable throwable) {
        Throwable current = throwable;
        while (current.getCause() != null) {
            current = current.getCause();
        }
        return current.getClass().getSimpleName();
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleUnexpectedException(Exception exception) {
        // Log it. This handler used to swallow every unexpected failure silently, which made a
        // 500 with no stack trace in the log impossible to diagnose.
        log.error("Unhandled exception while serving a request", exception);
        ErrorResponse response = ErrorResponse.of(
                "INTERNAL_ERROR",
                "Unexpected server error",
                List.of(exception.getClass().getSimpleName())
        );
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(response);
    }
}
