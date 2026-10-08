package com.fusionpilot.backend.dataset;

import com.fusionpilot.backend.account.AuthenticatedUser;
import com.fusionpilot.backend.account.UserService;
import com.fusionpilot.backend.api.ApiResponse;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v1/datasets")
public class DatasetController {

    private final UserService userService;
    private final DatasetImportService importService;

    public DatasetController(UserService userService, DatasetImportService importService) {
        this.userService = userService;
        this.importService = importService;
    }

    @PostMapping(value = "/import", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<DatasetImportSummary> importDataset(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestPart("file") MultipartFile file
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(importService.importZip(user.userId(), file));
    }
}
