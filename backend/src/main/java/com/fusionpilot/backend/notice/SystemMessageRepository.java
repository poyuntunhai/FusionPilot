package com.fusionpilot.backend.notice;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.List;
import java.util.Locale;
import java.util.Map;

@Repository
public class SystemMessageRepository {

    private final JdbcTemplate jdbcTemplate;

    public SystemMessageRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    /**
     * Published messages, newest first, each already flagged as read or not for {@code userId}.
     * Anonymous visitors pass null and get every row unread.
     */
    public List<SystemMessage> findPublished(Long userId) {
        return jdbcTemplate.query(
                """
                select m.message_id, m.title, m.body, m.version, m.level, m.published_at,
                       (r.read_at is not null) as is_read
                from fp_system_message m
                left join fp_system_message_read r
                       on r.message_id = m.message_id and r.user_id = ?
                where m.published_at <= current_timestamp
                order by m.published_at desc, m.message_id desc
                limit 50
                """,
                (resultSet, rowNum) -> new SystemMessage(
                        resultSet.getLong("message_id"),
                        resultSet.getString("title"),
                        resultSet.getString("body"),
                        resultSet.getString("version"),
                        resultSet.getString("level"),
                        resultSet.getTimestamp("published_at").toInstant(),
                        resultSet.getBoolean("is_read")
                ),
                // Anonymous callers have no read receipt row, so the join must simply not match.
                // -1 is never a real user_id (the column is auto_increment starting at 1), which
                // keeps this a single query instead of branching on null.
                userId == null ? -1L : userId
        );
    }

    public boolean existsPublished(long messageId) {
        Integer count = jdbcTemplate.queryForObject(
                """
                select count(*)
                from fp_system_message
                where message_id = ? and published_at <= current_timestamp
                """,
                Integer.class,
                messageId
        );
        return count != null && count > 0;
    }

    /**
     * Idempotent by design: opening a message twice keeps the first receipt, so {@code read_at}
     * stays the moment it was actually first read rather than the last time it was clicked.
     * Implemented as "insert, swallow the duplicate" instead of {@code ON DUPLICATE KEY UPDATE} so
     * the same statement works on MySQL and on the in-memory H2 the test suite runs against — and
     * so two callers racing to read the same message cannot both succeed in rewriting the time.
     */
    public void markRead(long messageId, long userId) {
        try {
            jdbcTemplate.update(
                    """
                    insert into fp_system_message_read (message_id, user_id)
                    values (?, ?)
                    """,
                    messageId,
                    userId
            );
        } catch (DuplicateKeyException alreadyRead) {
            // Nothing to do: the original receipt is the one worth keeping.
        }
    }

    public long insert(String title, String body, String version, String level) {
        // GeneratedKeyHolder rather than `select last_insert_id()`: it goes through the JDBC
        // getGeneratedKeys contract, which both MySQL and H2 honour.
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbcTemplate.update(
                connection -> {
                    PreparedStatement statement = connection.prepareStatement(
                            """
                            insert into fp_system_message (title, body, version, level)
                            values (?, ?, ?, ?)
                            """,
                            Statement.RETURN_GENERATED_KEYS
                    );
                    statement.setString(1, title);
                    statement.setString(2, body);
                    statement.setString(3, version);
                    statement.setString(4, level);
                    return statement;
                },
                keyHolder
        );
        return generatedMessageId(keyHolder);
    }

    /**
     * Pulls the new id out of whatever the driver decided to hand back.
     *
     * <p>There is no single shape here. H2 returns <em>every</em> column that has a default —
     * {@code message_id}, {@code published_at} and {@code created_at} — which makes
     * {@code getKey()} throw "the current key entry contains multiple keys"; MySQL returns one
     * column, and its label is not guaranteed to be the column name. Looking the id up by name and
     * falling back to the sole value covers both without a dialect switch.
     */
    private long generatedMessageId(KeyHolder keyHolder) {
        Map<String, Object> keys = keyHolder.getKeys();
        if (keys == null || keys.isEmpty()) {
            return 0L;
        }
        for (Map.Entry<String, Object> entry : keys.entrySet()) {
            if (entry.getKey() != null
                    && entry.getKey().toLowerCase(Locale.ROOT).contains("message_id")
                    && entry.getValue() instanceof Number number) {
                return number.longValue();
            }
        }
        Object only = keys.values().iterator().next();
        return only instanceof Number number ? number.longValue() : 0L;
    }
}
