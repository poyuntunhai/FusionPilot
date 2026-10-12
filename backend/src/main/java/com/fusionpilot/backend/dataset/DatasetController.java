package com.fusionpilot.backend.dataset;

import com.fusionpilot.backend.account.AuthenticatedUser;
import com.fusionpilot.backend.account.UserService;
import com.fusionpilot.backend.api.ApiResponse;
import com.fusionpilot.backend.api.ResourceNotFoundException;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@RestController
@RequestMapping("/api/v1/datasets")
public class DatasetController {

    private final UserService userService;
    private final DatasetImportService importService;
    private final DatasetRepository repository;

    public DatasetController(
            UserService userService,
            DatasetImportService importService,
            DatasetRepository repository
    ) {
        this.userService = userService;
        this.importService = importService;
        this.repository = repository;
    }

    @PostMapping(value = "/import", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<DatasetImportSummary> importDataset(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestPart("file") MultipartFile file
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(importService.importZip(user.userId(), file));
    }

    /**
     * The caller's own datasets, newest first.
     *
     * <p>Without this an uploaded dataset was write-only: the file was accepted, validated and
     * filed, and then nothing could read it back — least of all the person who uploaded it. The
     * simulation can now be pointed at one by id, which needs a way to discover the ids.
     */
    @GetMapping
    public ApiResponse<List<DatasetSummary>> listDatasets(
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(
                repository.findByUser(user.userId()).stream().map(DatasetSummary::of).toList()
        );
    }

    @GetMapping("/{datasetId}")
    public ApiResponse<DatasetSummary> getDataset(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @PathVariable String datasetId
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        DatasetRepository.DatasetRecord record = repository.findByIdAndUser(datasetId, user.userId());
        if (record == null) {
            // Same answer whether it does not exist or belongs to someone else: the difference is
            // itself information the caller has no business having.
            throw new ResourceNotFoundException("Dataset not found: " + datasetId);
        }
        return ApiResponse.ok(DatasetSummary.of(record));
    }
}
