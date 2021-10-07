from types import SimpleNamespace

__codes = {
    # 100 - 199 Errors
    # Execution Errors
    101: ("ExecutionScheduleTimeout", "Task could not be scheduled to run (either because it is already running or there are not enough execution slots available)"),
    102: ("ExecutionNotComplete", "Task could not complete (likely due to export service shutdown or crash)"),
    103: ("ExecutionRunTimeout", "Task ran over the allotted time and was cancelled"),

    # Docker errors
    110: ("DockerError", "An unexpected Docker error has occurred"),
    111: ("DockerAPIError", "A Docker API error has occurred"),
    112: ("DockerNotFound", "The Docker client was not able to find the requested resource or image"),
    113: ("DockerImageNotFound", "The Docker client was not able to find the requested image"),
    115: ("DockerInvalidRepository", "The Docker client requested access to an invalid repository"),
    116: ("DockerBuildError", "There was an error with the Docker build"),

    # Export API errors
    130: ("ExportAPIMalformedJSON", "The input supplied is invalid: malformed JSON"),
    131: ("ExportAPIProjectNotExist", "The input supplied is invalid: specified Domino Project does not exist"),
    132: ("ExportAPIProjectNoAccess", "Specified Domino API key does not have permission to the specified Domino Project"),
    133: ("ExportAPIExportNameConflict", "Specified Export Group Name and Project Name are already being exported as part of another export job"),
    134: ("ExportAPIDominoNameConflict", "Specified Domino Username and Project are already being exported as part of another export job"),
    135: ("ExportAPIExportIDNotExist", "Specified Export ID does not exist"),
    136: ("ExportAPIInvalidExportGroupName", "Export Group Name is invalid: name components may contain lowercase letters, digits and separators. A separator is defined as a period, one or two underscores, or one or more dashes. A name component may not start or end with a separator."),
    137: ("ExportAPIInvalidExportProjectName", "Export Project Name is invalid: name components may contain lowercase letters, digits and separators. A separator is defined as a period, one or two underscores, or one or more dashes. A name component may not start or end with a separator."),

    # Database Errors
    170: ("InvalidJobRunID", "Specified Job Run ID is invalid"),

    # Generic errors
    199: ("UnknownError", "An unexpected error has occurred: {EXCEPTION_TYPE}"),

    # 200 - 299 Generic status
    200: ("Skipped", "No action required"),
    205: ("Disabled", "Execution was skipped because job is disabled"),
    210: ("Initializing", "Execution has been created"),
    220: ("Scheduled", "Execution is scheduled to run"),
    290: ("Completed", "Execution has completed"),

    # 300 - 399 Running status
    300: ("Running", "Execution is running"),

    # 310 - 329 Project File Export stages
    310: ("ProjectFileExportInitiated", "Project file export has initiated"),
    311: ("ProjectFileDeletePriorStarted", "Started to cleanup the old project file export prior folder"),
    312: ("ProjectFileDeletePriorEnded", "Finished cleaning up the old project file export prior folder"),
    313: ("ProjectFileMoveLatestToPriorStarted", "Started to move the old project file export latest folder to the prior folder"),
    314: ("ProjectFileMoveLatestToPriorEnded", "Finished moving the old project file export latest folder to the prior folder"),
    315: ("ProjectFileTansferToS3Started", "Started to export the project files to the latest folder"),
    316: ("ProjectFileTansferToS3Ended", "Finished exporting the project files to the latest folder"),

    # 330 - 349 Docker Image Export stages
    330: ("DockerExportInitiated", "Docker image export has initiated"),
    331: ("DockerExportImagePullStarted", "Docker image for export is being pulled"),
    332: ("DockerExportImagePullEnded", "Docker image for export has been pulled"),
    333: ("DockerExportImageBuildStarted", "Docker image for export is being built"),
    334: ("DockerExportImageBuildEnded", "Docker image for export has been built"),
    335: ("DockerExportImagePushStarted", "Docker image for export is being pushed"),
    336: ("DockerExportImagePushEnded", "Docker image for export has been pushed")
}

StatusTypes = SimpleNamespace(**{
    "type": {k:v[0] for (k, v) in __codes.items()},
    "messageFromType": {v[0]:v[1] for (k, v) in __codes.items()},
    "message": {k:v[1] for (k, v) in __codes.items()},
    "code": {v[0]:k for (k, v) in __codes.items()}
})