package com.fusionpilot.backend.account;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.Instant;

@Repository
public class SessionRepository {

    private final JdbcTemplate jdbcTemplate;

    public SessionRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void insert(long userId, String tokenHash, Instant expiresAt) {
        jdbcTemplate.update(
                """
                insert into fp_user_session (user_id, token_hash, expires_at)
                values (?, ?, ?)
                """,
                userId,
                tokenHash,
                expiresAt
        );
    }

    public void revoke(String tokenHash) {
        jdbcTemplate.update(
                """
                update fp_user_session
                set revoked_at = current_timestamp
                where token_hash = ? and revoked_at is null
                """,
                tokenHash
        );
    }
}
