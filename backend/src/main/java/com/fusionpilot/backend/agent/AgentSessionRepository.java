package com.fusionpilot.backend.agent;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.sql.Types;
import java.util.LinkedHashMap;
import java.util.Map;

@Repository
public class AgentSessionRepository {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public AgentSessionRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public void save(long userId, JsonNode snapshot) {
        String traceId = snapshot.path("trace_id").asText();
        String goal = snapshot.path("request").path("goal").asText();
        String status = snapshot.path("status").asText("AWAITING_CONFIRMATION");
        boolean confirmed = snapshot.path("confirmed").asBoolean(false);
        String planJson = json(snapshot.path("plan"));
        String eventsJson = json(snapshot.path("events"));
        String lastResultJson = nullableJson(snapshot.get("last_result"));
        String analysisJson = nullableJson(snapshot.get("analysis"));

        int updated = jdbcTemplate.update(
                """
                update fp_agent_session
                set goal = ?, status = ?, confirmed = ?, plan_json = ?, events_json = ?,
                    last_result_json = ?, analysis_json = ?, updated_at = current_timestamp
                where trace_id = ? and user_id = ?
                """,
                statement -> {
                    statement.setString(1, goal);
                    statement.setString(2, status);
                    statement.setBoolean(3, confirmed);
                    statement.setString(4, planJson);
                    statement.setString(5, eventsJson);
                    setNullableJson(statement, 6, lastResultJson);
                    setNullableJson(statement, 7, analysisJson);
                    statement.setString(8, traceId);
                    statement.setLong(9, userId);
                }
        );
        if (updated == 0) {
            jdbcTemplate.update(
                    """
                    insert into fp_agent_session
                        (trace_id, user_id, goal, status, confirmed, plan_json, events_json,
                         last_result_json, analysis_json)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    statement -> {
                        statement.setString(1, traceId);
                        statement.setLong(2, userId);
                        statement.setString(3, goal);
                        statement.setString(4, status);
                        statement.setBoolean(5, confirmed);
                        statement.setString(6, planJson);
                        statement.setString(7, eventsJson);
                        setNullableJson(statement, 8, lastResultJson);
                        setNullableJson(statement, 9, analysisJson);
                    }
            );
        }
    }

    private void setNullableJson(PreparedStatement statement, int index, String value)
            throws java.sql.SQLException {
        if (value == null) {
            statement.setNull(index, Types.LONGVARCHAR);
        } else {
            statement.setString(index, value);
        }
    }

    public Map<String, Object> find(long userId, String traceId) {
        return jdbcTemplate.query(
                """
                select trace_id, user_id, goal, status, confirmed, plan_json, events_json,
                       last_result_json, analysis_json
                from fp_agent_session
                where trace_id = ? and user_id = ?
                """,
                resultSet -> resultSet.next() ? toSnapshot(resultSet) : null,
                traceId, userId
        );
    }

    private Map<String, Object> toSnapshot(java.sql.ResultSet resultSet) throws java.sql.SQLException {
        try {
            Map<String, Object> snapshot = new LinkedHashMap<>();
            snapshot.put("trace_id", resultSet.getString("trace_id"));
            snapshot.put("owner_user_id", resultSet.getLong("user_id"));
            snapshot.put("request", Map.of("goal", resultSet.getString("goal")));
            snapshot.put("plan", objectMapper.readTree(resultSet.getString("plan_json")));
            snapshot.put("confirmed", resultSet.getBoolean("confirmed"));
            snapshot.put("status", resultSet.getString("status"));
            snapshot.put("events", objectMapper.readTree(resultSet.getString("events_json")));
            snapshot.put("last_result", nullableNode(resultSet.getString("last_result_json")));
            snapshot.put("analysis", nullableNode(resultSet.getString("analysis_json")));
            return snapshot;
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored Agent trace JSON is invalid", exception);
        }
    }

    private String json(JsonNode node) {
        try {
            return objectMapper.writeValueAsString(node == null ? objectMapper.createArrayNode() : node);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("Agent trace cannot be serialized", exception);
        }
    }

    private String nullableJson(JsonNode node) {
        return node == null || node.isNull() ? null : json(node);
    }

    private JsonNode nullableNode(String value) throws JsonProcessingException {
        return value == null ? null : objectMapper.readTree(value);
    }
}
