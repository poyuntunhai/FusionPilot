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

    public AuthenticatedUser findActiveUser(String tokenHash) {
        return jdbcTemplate.query(
                """
                select u.user_id, u.username, u.email, u.display_name, u.role, u.status
                from fp_user_session s
                join fp_user u on u.user_id = s.user_id
                where s.token_hash = ?
                  and s.revoked_at is null
                  and s.expires_at > current_timestamp
                limit 1
                """,
                (resultSet, rowNum) -> new AuthenticatedUser(
                        resultSet.getLong("user_id"),
                        resultSet.getString("username"),
                        resultSet.getString("email"),
                        resultSet.getString("display_name"),
                        resultSet.getString("role"),
                        resultSet.getString("status")
                ),
                tokenHash
        ).stream().findFirst().orElse(null);
    }

    public void revokeAllForUser(long userId) {
        jdbcTemplate.update(
                """
                update fp_user_session
                set revoked_at = current_timestamp
                where user_id = ? and revoked_at is null
                """,
                userId
        );
    }
}
