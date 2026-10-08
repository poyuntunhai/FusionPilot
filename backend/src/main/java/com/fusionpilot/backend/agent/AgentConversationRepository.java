package com.fusionpilot.backend.agent;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.NullNode;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Types;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Storage for multi-turn agent conversations.
 *
 * A conversation is kept as one opaque snapshot. The transcript is expected to keep gaining
 * structure, and modelling it as columns would mean a migration per addition, so only the fields
 * the conversation list needs are lifted out into columns.
 *
 * Rows written by the earlier single-shot agent flow have no snapshot. {@link #find} treats those
 * as absent rather than trying to read them as conversations, which keeps the two shapes from
 * being confused for one another.
 */
@Repository
public class AgentConversationRepository {

    private static final int TITLE_LIMIT = 1000;

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public AgentConversationRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public void save(long userId, JsonNode snapshot) {
        String sessionId = text(snapshot, "session_id");
        if (sessionId.isBlank()) {
            throw new IllegalArgumentException("Conversation snapshot has no session_id");
        }
        String title = text(snapshot, "title");
        if (title.isBlank()) {
            title = "New conversation";
        }
        if (title.length() > TITLE_LIMIT) {
            title = title.substring(0, TITLE_LIMIT);
        }
        String status = text(snapshot, "status");
        if (status.isBlank()) {
            status = "ACTIVE";
        }
        // Reused column: for a conversation it means "nothing is waiting for the user".
        boolean settled = !snapshot.hasNonNull("pending") || snapshot.get("pending").isNull();
        String snapshotJson = serialize(snapshot);
        String summary = text(snapshot, "working_summary");
        String modelLabel = text(snapshot, "provider");
        String modelName = text(snapshot, "model");
        if (!modelName.isBlank()) {
            modelLabel = modelLabel.isBlank() ? modelName : modelLabel + ":" + modelName;
        }
        int messageCount = snapshot.path("messages").isArray() ? snapshot.path("messages").size() : 0;
        int toolCallCount = snapshot.path("tool_call_count").asInt(0);

        int updated = jdbcTemplate.update(
                """
                update fp_agent_session
                set goal = ?, status = ?, confirmed = ?, events_json = ?, snapshot_json = ?,
                    message_count = ?, tool_call_count = ?, model_label = ?, working_summary = ?,
                    updated_at = current_timestamp
                where trace_id = ? and user_id = ?
                """,
                title,
                status,
                settled,
                serialize(orEmptyArray(snapshot.get("events"))),
                snapshotJson,
                messageCount,
                toolCallCount,
                modelLabel.isBlank() ? null : trim(modelLabel, 120),
                summary.isBlank() ? null : trim(summary, 200),
                sessionId,
                userId
        );
        if (updated == 0) {
            jdbcTemplate.update(
                    """
                    insert into fp_agent_session
                        (trace_id, user_id, goal, status, confirmed, plan_json, events_json,
                         last_result_json, analysis_json, snapshot_json, message_count,
                         tool_call_count, model_label, working_summary)
                    values (?, ?, ?, ?, ?, ?, ?, null, null, ?, ?, ?, ?, ?)
                    """,
                    sessionId,
                    userId,
                    title,
                    status,
                    settled,
                    serialize(NullNode.getInstance()),
                    serialize(orEmptyArray(snapshot.get("events"))),
                    snapshotJson,
                    messageCount,
                    toolCallCount,
                    modelLabel.isBlank() ? null : trim(modelLabel, 120),
                    summary.isBlank() ? null : trim(summary, 200)
            );
        }
    }

    public Map<String, Object> find(long userId, String sessionId) {
        return jdbcTemplate.query(
                "select snapshot_json from fp_agent_session where trace_id = ? and user_id = ?",
                resultSet -> {
                    if (!resultSet.next()) {
                        return null;
                    }
                    String stored = resultSet.getString("snapshot_json");
                    return stored == null ? null : readSnapshot(stored);
                },
                sessionId,
                userId
        );
    }

    public List<Map<String, Object>> list(long userId, int limit) {
        int bounded = Math.max(1, Math.min(limit, 100));
        return jdbcTemplate.query(
                """
                select trace_id, goal, status, message_count, tool_call_count, model_label,
                       working_summary, created_at, updated_at
                from fp_agent_session
                where user_id = ? and snapshot_json is not null
                order by updated_at desc
                limit ?
                """,
                (resultSet, rowNum) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("session_id", resultSet.getString("trace_id"));
                    row.put("title", resultSet.getString("goal"));
                    row.put("status", resultSet.getString("status"));
                    String label = resultSet.getString("model_label");
                    row.put("provider", label == null ? "rule" : label);
                    row.put("model", null);
                    row.put("message_count", resultSet.getInt("message_count"));
                    row.put("tool_call_count", resultSet.getInt("tool_call_count"));
                    String summary = resultSet.getString("working_summary");
                    row.put("working_summary", summary == null ? "" : summary);
                    row.put("created_at", String.valueOf(resultSet.getTimestamp("created_at").toInstant()));
                    row.put("updated_at", String.valueOf(resultSet.getTimestamp("updated_at").toInstant()));
                    return row;
                },
                userId,
                bounded
        );
    }

    public int delete(long userId, String sessionId) {
        return jdbcTemplate.update(
                "delete from fp_agent_session where trace_id = ? and user_id = ? and snapshot_json is not null",
                sessionId,
                userId
        );
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> readSnapshot(String stored) {
        try {
            return objectMapper.readValue(stored, Map.class);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored conversation snapshot is not valid JSON", exception);
        }
    }

    private JsonNode orEmptyArray(JsonNode node) {
        return node == null || node.isNull() ? objectMapper.createArrayNode() : node;
    }

    private String serialize(JsonNode node) {
        try {
            return objectMapper.writeValueAsString(node == null ? NullNode.getInstance() : node);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("Conversation snapshot cannot be serialized", exception);
        }
    }

    private String text(JsonNode snapshot, String field) {
        JsonNode value = snapshot.get(field);
        return value == null || value.isNull() ? "" : value.asText("");
    }

    private String trim(String value, int limit) {
        return value.length() <= limit ? value : value.substring(0, limit);
    }
}
