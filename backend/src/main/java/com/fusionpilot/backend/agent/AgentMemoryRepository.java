package com.fusionpilot.backend.agent;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Long-term per-user agent memory.
 *
 * One row per user. The text is the agent's own distilled note (preferences and findings), so the
 * schema stays trivial and the content evolves as the agent learns without any migration.
 */
@Repository
public class AgentMemoryRepository {

    private final JdbcTemplate jdbcTemplate;

    public AgentMemoryRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public String get(long userId) {
        return jdbcTemplate.query(
                "select memory_text from fp_agent_memory where user_id = ?",
                resultSet -> resultSet.next() ? resultSet.getString("memory_text") : null,
                userId
        );
    }

    public void save(long userId, String memoryText) {
        String trimmed = memoryText == null ? "" : memoryText.trim();
        if (trimmed.isEmpty()) {
            jdbcTemplate.update("delete from fp_agent_memory where user_id = ?", userId);
            return;
        }
        int updated = jdbcTemplate.update(
                "update fp_agent_memory set memory_text = ?, updated_at = current_timestamp where user_id = ?",
                trimmed,
                userId
        );
        if (updated == 0) {
            jdbcTemplate.update(
                    "insert into fp_agent_memory (user_id, memory_text) values (?, ?)",
                    userId,
                    trimmed
            );
        }
    }
}
