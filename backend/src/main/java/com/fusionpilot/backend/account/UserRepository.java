package com.fusionpilot.backend.account;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

@Repository
public class UserRepository {

    private final JdbcTemplate jdbcTemplate;

    public UserRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public boolean existsByUsernameOrEmail(String username, String email) {
        Integer count = jdbcTemplate.queryForObject(
                "select count(*) from fp_user where username = ? or email = ?",
                Integer.class,
                username,
                email
        );
        return count != null && count > 0;
    }

    public UserProfile insert(String username, String email, String passwordHash, String displayName) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(connection -> {
            PreparedStatement statement = connection.prepareStatement(
                    """
                    insert into fp_user
                        (username, email, password_hash, display_name, role, status)
                    values (?, ?, ?, ?, 'USER', 'ACTIVE')
                    """,
                    new String[]{"user_id"}
            );
            statement.setString(1, username);
            statement.setString(2, email);
            statement.setString(3, passwordHash);
            statement.setString(4, displayName);
            return statement;
        }, keyHolder);
        Number key = keyHolder.getKey();
        if (key == null) {
            throw new IllegalStateException("User id was not generated");
        }
        return new UserProfile(key.longValue(), username, email, displayName, "USER", "ACTIVE");
    }

    public Optional<UserCredentials> findCredentials(String login) {
        return jdbcTemplate.query(
                """
                select user_id, username, email, password_hash, display_name, role, status
                from fp_user
                where username = ? or email = ?
                limit 1
                """,
                (resultSet, rowNum) -> new UserCredentials(
                        resultSet.getLong("user_id"),
                        resultSet.getString("username"),
                        resultSet.getString("email"),
                        resultSet.getString("password_hash"),
                        resultSet.getString("display_name"),
                        resultSet.getString("role"),
                        resultSet.getString("status")
                ),
                login,
                login
        ).stream().findFirst();
    }

    public void markLogin(long userId) {
        jdbcTemplate.update(
                "update fp_user set last_login_at = current_timestamp where user_id = ?",
                userId
        );
    }

    public void updatePassword(long userId, String passwordHash) {
        jdbcTemplate.update(
                "update fp_user set password_hash = ?, updated_at = current_timestamp where user_id = ?",
                passwordHash,
                userId
        );
    }

    public List<AdminUserSummary> findAllUsers() {
        return jdbcTemplate.query(
                """
                select user_id, username, email, display_name, role, status, last_login_at, created_at
                from fp_user
                order by created_at desc
                """,
                (resultSet, rowNum) -> new AdminUserSummary(
                        resultSet.getLong("user_id"),
                        resultSet.getString("username"),
                        resultSet.getString("email"),
                        resultSet.getString("display_name"),
                        resultSet.getString("role"),
                        resultSet.getString("status"),
                        toInstant(resultSet.getTimestamp("last_login_at")),
                        toInstant(resultSet.getTimestamp("created_at"))
                )
        );
    }

    public void updateStatus(long userId, String status) {
        jdbcTemplate.update(
                "update fp_user set status = ?, updated_at = current_timestamp where user_id = ?",
                status,
                userId
        );
    }

    private Instant toInstant(Timestamp timestamp) {
        return timestamp == null ? null : timestamp.toInstant();
    }
}
