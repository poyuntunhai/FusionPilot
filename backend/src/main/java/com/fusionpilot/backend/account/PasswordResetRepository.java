package com.fusionpilot.backend.account;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.Instant;

@Repository
public class PasswordResetRepository {

    private final JdbcTemplate jdbcTemplate;

    public PasswordResetRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void invalidateForUser(long userId) {
        jdbcTemplate.update(
                "update fp_password_reset_token set used_at = current_timestamp where user_id = ? and used_at is null",
                userId
        );
    }

    public void insert(long userId, String tokenHash, Instant expiresAt) {
        jdbcTemplate.update(
                """
                insert into fp_password_reset_token (user_id, token_hash, expires_at)
                values (?, ?, ?)
                """,
                userId,
                tokenHash,
                expiresAt
        );
    }

    public ResetToken findValid(String tokenHash) {
        return jdbcTemplate.query(
                """
                select reset_id, user_id
                from fp_password_reset_token
                where token_hash = ?
                  and used_at is null
                  and expires_at > current_timestamp
                limit 1
                """,
                (resultSet, rowNum) -> new ResetToken(
                        resultSet.getLong("reset_id"),
                        resultSet.getLong("user_id")
                ),
                tokenHash
        ).stream().findFirst().orElse(null);
    }

    public void markUsed(long resetId) {
        jdbcTemplate.update(
                "update fp_password_reset_token set used_at = current_timestamp where reset_id = ? and used_at is null",
                resetId
        );
    }

    public record ResetToken(long resetId, long userId) {
    }
}
