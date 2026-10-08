package com.fusionpilot.backend.dataset;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

@Service
public class DatasetImportService {

    private static final long MAX_ENTRY_BYTES = 50L * 1024 * 1024;
    private static final Set<String> REQUIRED_MANIFEST_FIELDS = Set.of(
            "schema_version", "coordinate_frame", "units", "time_convention"
    );
    private static final Set<String> REQUIRED_OBSERVATION_COLUMNS = Set.of(
            "time_step", "sensor_id", "source_type", "x", "y"
    );
    private static final Set<String> REQUIRED_TRUTH_COLUMNS = Set.of(
            "time_step", "target_id", "x", "y"
    );

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final Path storageRoot;

    public DatasetImportService(
            JdbcTemplate jdbcTemplate,
            ObjectMapper objectMapper,
            @Value("${fusionpilot.storage.dataset-root:runtime/datasets}") String storageRoot
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.storageRoot = Path.of(storageRoot).toAbsolutePath().normalize();
    }

    public DatasetImportSummary importZip(long userId, MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new DatasetImportException("Dataset file is empty");
        }
        String fileName = file.getOriginalFilename() == null ? "" : file.getOriginalFilename();
        if (!fileName.toLowerCase().endsWith(".zip")) {
            throw new DatasetImportException("Only ZIP dataset packages are supported");
        }

        String datasetId = UUID.randomUUID().toString();
        Path datasetDirectory = storageRoot.resolve(Long.toString(userId)).resolve(datasetId).normalize();
        if (!datasetDirectory.startsWith(storageRoot)) {
            throw new DatasetImportException("Invalid dataset storage path");
        }

        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        int truthRows = 0;
        int observationRows = 0;
        try {
            Files.createDirectories(datasetDirectory);
            Path rawFile = datasetDirectory.resolve("source.zip");
            Files.copy(file.getInputStream(), rawFile, StandardCopyOption.REPLACE_EXISTING);
            Map<String, byte[]> entries = readEntries(rawFile);
            byte[] manifest = entries.get("manifest.json");
            if (manifest == null) {
                errors.add("manifest.json is required");
            } else {
                validateManifest(manifest, errors);
            }
            byte[] observations = entries.get("observations.csv");
            if (observations == null) {
                errors.add("observations.csv is required");
            } else {
                observationRows = validateCsv(observations, REQUIRED_OBSERVATION_COLUMNS, "observations.csv", errors);
            }
            byte[] truth = entries.get("truth.csv");
            if (truth != null) {
                truthRows = validateCsv(truth, REQUIRED_TRUTH_COLUMNS, "truth.csv", errors);
            } else {
                warnings.add("truth.csv is absent; trajectory display is possible but error metrics are unavailable");
            }
            String status = errors.isEmpty() ? "VALIDATED" : "REJECTED";
            Instant createdAt = Instant.now();
            jdbcTemplate.update(
                    """
                    insert into fp_dataset
                        (dataset_id, user_id, file_name, file_size, storage_path, status,
                         truth_rows, observation_rows, errors_json, warnings_json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    datasetId,
                    userId,
                    file.getOriginalFilename(),
                    file.getSize(),
                    rawFile.toString(),
                    status,
                    truthRows,
                    observationRows,
                    objectMapper.writeValueAsString(errors),
                    objectMapper.writeValueAsString(warnings),
                    createdAt
            );
            return new DatasetImportSummary(
                    datasetId, file.getOriginalFilename(), file.getSize(), status,
                    truthRows, observationRows, List.copyOf(errors),
                    List.copyOf(warnings), createdAt
            );
        } catch (IOException exception) {
            throw new DatasetImportException("Could not read dataset package", exception);
        } catch (Exception exception) {
            throw new DatasetImportException("Could not persist dataset metadata", exception);
        }
    }

    private Map<String, byte[]> readEntries(Path zipPath) throws IOException {
        Map<String, byte[]> entries = new HashMap<>();
        try (InputStream input = Files.newInputStream(zipPath);
             ZipInputStream zip = new ZipInputStream(input, StandardCharsets.UTF_8)) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                if (entry.isDirectory()) continue;
                String name = Path.of(entry.getName()).normalize().toString().replace('\\', '/');
                if (name.contains("..") || name.startsWith("/")) {
                    throw new DatasetImportException("Unsafe ZIP entry: " + entry.getName());
                }
                if (Set.of("manifest.json", "truth.csv", "observations.csv").contains(name)) {
                    byte[] bytes = zip.readAllBytes();
                    if (bytes.length > MAX_ENTRY_BYTES) {
                        throw new DatasetImportException("Dataset entry is larger than 50 MB: " + name);
                    }
                    entries.put(name, bytes);
                }
            }
        }
        return entries;
    }

    private void validateManifest(byte[] bytes, List<String> errors) throws IOException {
        Map<?, ?> manifest = objectMapper.readValue(bytes, Map.class);
        for (String field : REQUIRED_MANIFEST_FIELDS) {
            if (!manifest.containsKey(field) || manifest.get(field) == null
                    || manifest.get(field).toString().isBlank()) {
                errors.add("manifest.json field is required: " + field);
            }
        }
    }

    private int validateCsv(
            byte[] bytes,
            Set<String> requiredColumns,
            String name,
            List<String> errors
    ) throws IOException {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                new java.io.ByteArrayInputStream(bytes), StandardCharsets.UTF_8))) {
            String headerLine = reader.readLine();
            if (headerLine == null) {
                errors.add(name + " is empty");
                return 0;
            }
            Set<String> headers = new HashSet<>();
            for (String header : headerLine.split(",", -1)) {
                headers.add(header.trim());
            }
            for (String required : requiredColumns) {
                if (!headers.contains(required)) {
                    errors.add(name + " missing column: " + required);
                }
            }
            int rows = 0;
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.isBlank()) rows++;
            }
            if (rows == 0) errors.add(name + " has no data rows");
            return rows;
        }
    }
}
