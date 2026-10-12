package com.fusionpilot.backend.dataset;

import java.time.Instant;
import java.util.List;

/**
 * What a client is allowed to know about a dataset.
 *
 * <p>Deliberately not {@link DatasetRepository.DatasetRecord}: that carries the server-side storage
 * path, which is nobody's business outside this process and would leak the filesystem layout to
 * anyone who can read their own dataset list.
 */
public record DatasetSummary(
        String datasetId,
        String fileName,
        long fileSize,
        String status,
        int truthRows,
        int observationRows,
        List<String> errors,
        List<String> warnings,
        /**
         * Whether this dataset can drive a simulation — validated and carrying truth.csv. The UI
         * uses it to grey out the rest rather than letting a run fail after it was submitted.
         */
        boolean usableAsTruth,
        Instant createdAt
) {
    static DatasetSummary of(DatasetRepository.DatasetRecord record) {
        return new DatasetSummary(
                record.datasetId(),
                record.fileName(),
                record.fileSize(),
                record.status(),
                record.truthRows(),
                record.observationRows(),
                record.errors(),
                record.warnings(),
                record.isRunnableAsTruth(),
                record.createdAt()
        );
    }
}
