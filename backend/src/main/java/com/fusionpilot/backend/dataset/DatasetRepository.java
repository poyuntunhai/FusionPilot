package com.fusionpilot.backend.dataset;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.List;

@Repository
public class DatasetRepository {

    private static final TypeReference<List<String>> STRING_LIST = new TypeReference<>() {
    };

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public DatasetRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    /**
     * A stored dataset row.
     *
     * <p>{@code errors} and {@code warnings} are parsed out of the JSON columns here rather than
     * carried around as strings, so a caller cannot forget to decode them and render
     * {@code ["missing column: x"]} at the user.
     */
    public record DatasetRecord(
            String datasetId,
            long userId,
            String fileName,
            long fileSize,
            String storagePath,
            String status,
            int truthRows,
            int observationRows,
            List<String> errors,
            List<String> warnings,
            Instant createdAt
    ) {
        /** Only a validated dataset with ground truth can drive a simulation. */
        public boolean isRunnableAsTruth() {
            return "VALIDATED".equals(status) && truthRows > 0;
        }
    }

    public List<DatasetRecord> findByUser(long userId) {
        return jdbcTemplate.query(
                """
                select dataset_id, user_id, file_name, file_size, storage_path, status,
                       truth_rows, observation_rows, errors_json, warnings_json, created_at
                from fp_dataset
                where user_id = ?
                order by created_at desc
                """,
                this::mapRow,
                userId
        );
    }

    public DatasetRecord findByIdAndUser(String datasetId, long userId) {
        return jdbcTemplate.query(
                """
                select dataset_id, user_id, file_name, file_size, storage_path, status,
                       truth_rows, observation_rows, errors_json, warnings_json, created_at
                from fp_dataset
                where dataset_id = ? and user_id = ?
                """,
                this::mapRow,
                datasetId,
                userId
        ).stream().findFirst().orElse(null);
    }

    /**
     * Look a dataset up by id alone.
     *
     * <p>Deliberately owner-less: this is the path the observation layer uses while generating a
     * sample, where there is no user in scope. Ownership is enforced where the user *is* in scope —
     * when the configuration is accepted — so adding a check here would mean threading a user id
     * through the simulation core to re-ask a question already answered.
     */
    public DatasetRecord findById(String datasetId) {
        return jdbcTemplate.query(
                """
                select dataset_id, user_id, file_name, file_size, storage_path, status,
                       truth_rows, observation_rows, errors_json, warnings_json, created_at
                from fp_dataset
                where dataset_id = ?
                """,
                this::mapRow,
                datasetId
        ).stream().findFirst().orElse(null);
    }

    private DatasetRecord mapRow(ResultSet resultSet, int rowNum) throws SQLException {
        return new DatasetRecord(
                resultSet.getString("dataset_id"),
                resultSet.getLong("user_id"),
                resultSet.getString("file_name"),
                resultSet.getLong("file_size"),
                resultSet.getString("storage_path"),
                resultSet.getString("status"),
                resultSet.getInt("truth_rows"),
                resultSet.getInt("observation_rows"),
                decode(resultSet.getString("errors_json")),
                decode(resultSet.getString("warnings_json")),
                resultSet.getTimestamp("created_at").toInstant()
        );
    }

    private List<String> decode(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(json, STRING_LIST);
        } catch (Exception exception) {
            // A malformed column must not take the whole listing down; the raw text is still worth
            // showing, and the import that wrote it already recorded the problem.
            return List.of(json);
        }
    }
}
