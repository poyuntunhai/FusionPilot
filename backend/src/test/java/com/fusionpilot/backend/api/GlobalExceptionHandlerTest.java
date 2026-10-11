package com.fusionpilot.backend.api;

import org.junit.jupiter.api.Test;
import org.springframework.dao.TransientDataAccessResourceException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Database failures used to fall through to the catch-all handler, so the client got
 * "Unexpected server error" with a class name — which is how a result too big for the database's
 * {@code max_allowed_packet} looked: the simulation had already finished, only the save failed, and
 * the message told nobody anything.
 *
 * <p>The detection is by class <em>name</em> because both JDBC drivers are declared {@code runtime}
 * scope (the application deliberately starts against either H2 or MySQL), so their exception types
 * cannot be referenced from here. The nested fake below is that name, which is exactly the part that
 * could silently stop matching.
 */
class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    /** Named to match what the MySQL driver throws, without depending on the driver. */
    private static final class PacketTooBigException extends RuntimeException {
        private PacketTooBigException() {
            super("Packet for query is too large (27,239,074 > 4,194,304)");
        }
    }

    @Test
    void aPacketTooBigFailureBecomesAnActionableAnswer() {
        ResponseEntity<ErrorResponse> response = handler.handleDataAccess(
                new TransientDataAccessResourceException("insert failed", new PacketTooBigException()));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.PAYLOAD_TOO_LARGE);
        ErrorResponse body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.code()).isEqualTo("RESULT_TOO_LARGE");
        // The whole point: the message has to say what to do about it.
        assertThat(body.message()).contains("max_allowed_packet").contains("规模");
    }

    @Test
    void theCauseIsLookedUpThroughWrapping() {
        // Spring wraps driver exceptions at least twice; a shallow check would miss the real cause.
        TransientDataAccessResourceException wrapped = new TransientDataAccessResourceException(
                "outer",
                new IllegalStateException("middle", new PacketTooBigException()));

        assertThat(handler.handleDataAccess(wrapped).getStatusCode())
                .isEqualTo(HttpStatus.PAYLOAD_TOO_LARGE);
    }

    @Test
    void anyOtherDatabaseFailureStillSaysSomethingReadable() {
        ResponseEntity<ErrorResponse> response = handler.handleDataAccess(
                new TransientDataAccessResourceException("connection reset", new java.io.IOException("boom")));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        ErrorResponse body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.message()).isEqualTo("数据库操作失败，请稍后重试。");
        // The root cause is still named, for whoever has to debug it.
        assertThat(body.details()).containsExactly("IOException");
    }
}
