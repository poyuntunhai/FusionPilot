package com.fusionpilot.backend.dataset;

import java.time.Instant;
import java.util.List;

public record DatasetImportSummary(
        String datasetId,
        String fileName,
        long fileSize,
        String status,
        int truthRows,
        int observationRows,
        List<String> errors,
        List<String> warnings,
        Instant createdAt
) {
}
