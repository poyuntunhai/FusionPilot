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
