import app.models as models
from app import db
from app import encrypter
from app.dbcommon import DBCommon
from domino import DominoAPISession
from domino import DominoAPIKeyInvalid, DominoAPIUnauthorized, DominoAPINotFound, DominoAPIBadRequest, DominoAPIComputeEnvironmentRevisionNotAvailable, DominoAPIUnexpectedError
from app.dockerclient import DockerClient
from app.dockerclient import DockerException, DockerAPIError, DockerNotFound, DockerImageNotFound, DockerInvalidRepository, DockerBuildError
from app.helpers import S3Helpers, DBHelpers
from app.status import StatusTypes

import json
from time import time
from time import sleep
import boto3
import stopit
from urllib.parse import urlparse
from smart_open import open
import logging

class BaseExecution(object):
    def __init__(self, executionID, scheduler):
        self._scheduler = scheduler
        self._dbSession = db.dbSession
        self._dbCommon = DBCommon(self._dbSession)
        self._execution = self._dbCommon.getExecution(executionID)
        self._jobRun = self._dbCommon.getJobRun(self._execution.job_id, self._execution.job_run_id, self._execution.execution_type)
        self._logger = logging.getLogger(__name__)

        try:
            self.start()
            self.run()
        except Exception as e:
            raise(e)
        finally:
            self.stop()

    def start(self):
        self.setStartTimestamp()

    def run(self):
        from app import app

        if not self._execution.jobs.job_active:
            self.setExecutionStatus(StatusTypes.code["Disabled"])
        else:
            self.setExecutionStatus(StatusTypes.code["Running"])

            try:
                taskStatus = self.defaultTask(timeout = app.config["JOB_TASK_TIMEOUT_IN_SECONDS"])
                if taskStatus:
                    self.setExecutionStatus(taskStatus)
                else:
                    self.setExecutionStatus(StatusTypes.code["Completed"])
            except Exception as e:
                exceptionType = type(e).__name__
                self.setExecutionStatus(StatusTypes.code.get(exceptionType, StatusTypes.code["UnknownError"]))
                self.saveExceptionDetails(exceptionType, str(e))
                raise(e)

    def stop(self):
        self.setEndTimestamp()

    @stopit.threading_timeoutable(default=StatusTypes.code["ExecutionRunTimeout"])
    def defaultTask(self):
        pass

    def updateJobRun(self, successfulExecutionID = None):
        if successfulExecutionID:
            self._jobRun.last_successful_execution_id = successfulExecutionID
        else:
            self._jobRun.last_successful_execution_id = self._execution.execution_id

        self._jobRun.job_run_updated_timestamp = DBHelpers.now()
        self._dbSession.commit()

    def updateJobTaskStates(self, taskStates):
        jobDetails = json.loads(encrypter.decrypt(self._execution.jobs.job_details))

        if "taskState" not in jobDetails:
             jobDetails["taskState"] = {}

        for taskUpdate in taskStates:
            task = taskUpdate.get("task", None)
            taskInfo = taskUpdate.get("taskInfo", {})

            if task in jobDetails["taskState"]:
                jobDetails["taskState"][task].update(taskInfo)
            elif task:
                jobDetails["taskState"][task] = taskInfo

        self._execution.jobs.job_details = encrypter.encrypt(json.dumps(jobDetails))
        self._dbSession.commit()

    def updateExecutionDetails(self, newInfo):
        executionDetails = {}
        if self._execution.execution_details:
            executionDetails = json.loads(encrypter.decrypt(self._execution.execution_details))

        executionDetails.update(newInfo)
        self._execution.execution_details = encrypter.encrypt(json.dumps(executionDetails))
        self._dbSession.commit()

    def saveExceptionDetails(self, exceptionType, exceptionMessage):
        self.updateExecutionDetails({
            "exception": {
                "EXCEPTION_TYPE": exceptionType,
                "EXCEPTION_DETAILS": exceptionMessage
            }
        })

    def setExecutionStatus(self, statusCode):
        self._execution.execution_status = statusCode
        self._dbSession.commit()

    def setStartTimestamp(self):
        self._execution.execution_started_timestamp = DBHelpers.now()
        self._dbSession.commit()

    def setEndTimestamp(self):
        self._execution.execution_ended_timestamp = DBHelpers.now()
        self._dbSession.commit()


class BaseJob(object):
    def __init__(self, jobID, scheduler):
        self._waitCheckIntervalSeconds = 5
        self._scheduler = scheduler
        self._dbSession = db.dbSession
        self._dbCommon = DBCommon(self._dbSession)
        self._jobID = jobID
        self._job = self._dbCommon.getJob(jobID)
        self._jobRunID = self._dbCommon.getNextJobRunID(jobID)
        self._logger = logging.getLogger(__name__)

    def isJobAlreadyRunning(self):
        return self._dbCommon.isJobRunning(self._jobID)

    def run(self):
        for execution in self._dbCommon.getRunningExecutionsForJobRun(self._jobID, self._jobRunID):
            self._scheduler.addExecution(execution.execution_id)

    def wait(self):
        while self._dbCommon.getRunningExecutionsForJobRun(self._jobID, self._jobRunID):
            sleep(self._waitCheckIntervalSeconds)

    def addExecution(self, execution):
        self._dbSession.add(execution)
        # Need to commit to generate execution_id to use below
        self._dbSession.commit()

        self._dbSession.add(
            models.JobRun(
                job_id = self._jobID,
                job_run_id = self._jobRunID,
                execution_type = execution.execution_type,
                associated_execution_id = execution.execution_id,
                last_successful_execution_id = None
            )
        )
        self._dbSession.commit()

    def addSubTasks(self, tasks):
        for task in tasks:
            execution = models.Execution(
                execution_type = task,
                job_run_id = self._jobRunID,
                job_id = self._jobID,
                execution_details = encrypter.encrypt(json.dumps({
                    "exception": {
                        "EXCEPTION_TYPE": None,
                        "EXCEPTION_DETAILS": None
                    }
                }))
            )
            execution.execution_status = StatusTypes.code["Scheduled"]

            self.addExecution(execution)

class ProjectFilesExportTask(BaseExecution):
    @stopit.threading_timeoutable(default=StatusTypes.code["ExecutionRunTimeout"])
    def defaultTask(self):
        from app import app
        taskStatus = None

        self.updateExecutionDetails(
            {
                "commitID": None,
                "S3Paths": {
                    "latest": None,
                    "prior": None
                }
            }
        )

        jobDetails = json.loads(encrypter.decrypt(self._execution.jobs.job_details))
        dominoAPIKey = encrypter.decrypt(self._execution.jobs.job_secrets)
        dominoUsername = self._execution.jobs.job_user
        dominoProjectName = self._execution.jobs.job_project
        exportGroupName = self._execution.jobs.job_export_group
        exportProjectName = self._execution.jobs.job_export_project

        dominoAPI = DominoAPISession(app.config["DOMINO_API_SERVER"], dominoAPIKey, verifySSL = app.config["DOMINO_API_SERVER_VERIFY_SSL"])
        projectInfo = dominoAPI.findProjectByOwnerAndName(dominoUsername, dominoProjectName)
        projectFiles = dominoAPI.projectListLatestFilesByProjectID(projectInfo["id"]).get("files", [])
        projectCommits = dominoAPI.projectCommitIDs(dominoUsername, dominoProjectName).get("commits", [])
        projectLatestCommitID = sorted(projectCommits, key = lambda i: i["commitTime"], reverse = True)[0]["id"] if len(projectCommits) else None
        priorExportedCommitID = jobDetails.get("taskState", {}).get("ProjectFilesExportTask", {}).get("commitID", None)

        if app.config["EXPORTS_PROJECT_FILES_FORCE_RUN"] or (projectLatestCommitID != priorExportedCommitID):
            exportsS3Path = app.config["EXPORTS_PROJECT_FILES_S3_PATH_FORMAT"].format(
                S3_BUCKET = app.config["EXPORTS_PROJECT_FILES_S3_BUCKET"],
                DOMINO_USERNAME = dominoUsername,
                DOMINO_PROJECT_NAME = dominoProjectName,
                EXPORT_GROUP_NAME = exportGroupName,
                EXPORT_PROJECT_NAME = exportProjectName
            )

            exportS3PathLatest = app.config["EXPORTS_PROJECT_FILES_S3_LATEST_FORMAT"].format(
                S3_BUCKET = app.config["EXPORTS_PROJECT_FILES_S3_BUCKET"],
                DOMINO_USERNAME = dominoUsername,
                DOMINO_PROJECT_NAME = dominoProjectName,
                EXPORT_GROUP_NAME = exportGroupName,
                EXPORT_PROJECT_NAME = exportProjectName,
                EXPORTS_PROJECT_FILES_S3_PATH = exportsS3Path
            )
            exportS3PathLatestParsed = urlparse(exportS3PathLatest)
            exportS3PathPrior = app.config["EXPORTS_PROJECT_FILES_S3_PRIOR_FORMAT"].format(
                S3_BUCKET = app.config["EXPORTS_PROJECT_FILES_S3_BUCKET"],
                DOMINO_USERNAME = dominoUsername,
                DOMINO_PROJECT_NAME = dominoProjectName,
                EXPORT_GROUP_NAME = exportGroupName,
                EXPORT_PROJECT_NAME = exportProjectName,
                EXPORTS_PROJECT_FILES_S3_PATH = exportsS3Path
            )
            exportS3PathPriorParsed = urlparse(exportS3PathPrior)

            self.setExecutionStatus(StatusTypes.code["ProjectFileExportInitiated"])
            s3 = boto3.resource("s3")
            priorS3Path = exportS3PathPriorParsed.path.lstrip("/")
            latestS3Path = exportS3PathLatestParsed.path.lstrip("/")
            
            #print("Deleting prior project files export {0}".format(exportS3PathPrior))
            self.setExecutionStatus(StatusTypes.code["ProjectFileDeletePriorStarted"])
            S3Helpers.delete(s3, exportS3PathLatestParsed.netloc, priorS3Path)
            self.setExecutionStatus(StatusTypes.code["ProjectFileDeletePriorEnded"])

            #print("Moving prior project files export to {0}".format(exportS3PathPrior))
            self.setExecutionStatus(StatusTypes.code["ProjectFileMoveLatestToPriorStarted"])
            S3Helpers.move(s3, exportS3PathLatestParsed.netloc, latestS3Path, priorS3Path)
            self.setExecutionStatus(StatusTypes.code["ProjectFileMoveLatestToPriorEnded"])

            #print("Starting project files export for {0}/{1} to {2}/{3}".format(dominoUsername, dominoProjectName, exportGroupName, exportProjectName))
            self.setExecutionStatus(StatusTypes.code["ProjectFileTansferToS3Started"])
            for file in projectFiles:
                s3FilePath = "{0}/{1}".format(
                    exportS3PathLatest,
                    file["path"]["canonicalizedPathString"]
                )

                # print("Saving {0}/{1}/{2} ({3}) to {4}...".format(
                #     dominoUsername,
                #     dominoProjectName,
                #     file["path"]["canonicalizedPathString"],
                #     DBHelpers.human_readable_size(file["size"]),
                #     s3FilePath
                # ))

                with open(s3FilePath, "wb") as s3FileSave:
                    for chunk in dominoAPI.projectFileContentsByKeyID(dominoUsername, dominoProjectName, file["key"]):
                        s3FileSave.write(chunk)
                    #print("Saved {0}\n".format(s3FilePath))
            self.setExecutionStatus(StatusTypes.code["ProjectFileTansferToS3Ended"])

            self.updateExecutionDetails(
                {
                    "commitID": projectLatestCommitID,
                    "S3Paths": {
                        "latest": exportS3PathLatest,
                        "prior": exportS3PathPrior
                    }
                }
            )
            self.updateJobRun()
            # Ensure we don't push the same image again in the future
            self.updateJobTaskStates(
                [
                    {
                        "task": "ProjectFilesExportTask",
                        "taskInfo": {
                            "lastCompletedExecutionID": self._execution.execution_id,
                            "commitID": projectLatestCommitID
                        }
                    },
                    {
                        "task": "ProjectExportReportToS3Task", 
                        "taskInfo": {
                            "statusSaved": False,
                        }
                    }
                ]
            )
        else:
            #print("Skipping project files export for {0}/{1} to {2}/{3}".format(dominoUsername, dominoProjectName, exportGroupName, exportProjectName))
            taskStatus = StatusTypes.code["Skipped"]
            self.updateJobRun(jobDetails.get("taskState", {}).get("ProjectFilesExportTask", {}).get("lastCompletedExecutionID", None))

        return taskStatus

class ProjectDockerImageExportTask(BaseExecution):
    @stopit.threading_timeoutable(default=StatusTypes.code["ExecutionRunTimeout"])
    def defaultTask(self):
        from app import app
        taskStatus = None

        jobDetails = json.loads(encrypter.decrypt(self._execution.jobs.job_details))
        dominoAPIKey = encrypter.decrypt(self._execution.jobs.job_secrets)
        dominoUsername = self._execution.jobs.job_user
        dominoProjectName = self._execution.jobs.job_project
        exportGroupName = self._execution.jobs.job_export_group
        exportProjectName = self._execution.jobs.job_export_project

        dominoAPI = DominoAPISession(app.config["DOMINO_API_SERVER"], dominoAPIKey, verifySSL = app.config["DOMINO_API_SERVER_VERIFY_SSL"])
        computeEnvironmentRevision = dominoAPI.projectComputeEnvironmentAndRevision(dominoUsername, dominoProjectName)
        computeEnvironmentDetails = dominoAPI.environmentDetailByID(computeEnvironmentRevision["id"])
        priorExportedcomputeEnvironmentID = jobDetails.get("taskState", {}).get("ProjectDockerImageExportTask", {}).get("computeEnvironmentID", None)
        priorExportedcomputeEnvironmentRevision = jobDetails.get("taskState", {}).get("ProjectDockerImageExportTask", {}).get("computeEnvironmentRevision", None)
        computeEnvironmentURL = dominoAPI.environmentURLByRevision(computeEnvironmentRevision["id"], computeEnvironmentRevision["revision"])

        dockerFileTemplatePath = "{0}/{1}".format(
            app.config["DOCKER_BUILD_TEMPLATE_PATH"],
            jobDetails["dockerBuildTemplateFile"]
        )

        if computeEnvironmentURL.startswith("http"):
            registryURLParsed = urlparse(computeEnvironmentURL)
        else:
            registryURLParsed = urlparse("{0}://{1}".format("https", computeEnvironmentURL))

        # Automatically set the global DOMINO_DOCKER_REGISTRY if it is not already set
        if not app.config.get("DOMINO_DOCKER_REGISTRY", None):
            app.config["DOMINO_DOCKER_REGISTRY"] = "{0}".format(registryURLParsed.netloc)

        # Debug purposes
        if app.config.get("DOMINO_DOCKER_IMAGE_FORMAT", None):
            computeEnvironmentURL = app.config["DOMINO_DOCKER_IMAGE_FORMAT"].format(
                DOCKER_REGISTRY = app.config["DOMINO_DOCKER_REGISTRY"],
                DOMINO_COMPUTE_ENVIRONMENT_ID = computeEnvironmentRevision["id"],
                DOMINO_COMPUTE_ENVIRONMENT_REVISION = computeEnvironmentRevision["revision"]
            )

        dominoRegistry = {
            "url": app.config["DOMINO_DOCKER_REGISTRY"],
            "username": app.config.get("DOMINO_DOCKER_REGISTRY_USER", None),
            "password": app.config.get("DOMINO_DOCKER_REGISTRY_PASSWORD", None)
        }
        externalRegistry = {
            "url": app.config["EXPORTS_DOCKER_REGISTRY"],
            "username": app.config.get("EXPORTS_DOCKER_REGISTRY_USERNAME", None),
            "password": app.config.get("EXPORTS_DOCKER_REGISTRY_PASSWORD", None)
        }
        dockerClient = DockerClient(dominoRegistry, externalRegistry)
        dockerClient.raiseOnException(True)
        self.setExecutionStatus(StatusTypes.code["DockerExportInitiated"])

        # Concat the Compute Env ID and Revision ID for easy comparison
        savedComputeEnvironment = "{ENV_ID}-{ENV_REVISION}".format(
            ENV_ID = priorExportedcomputeEnvironmentID,
            ENV_REVISION = priorExportedcomputeEnvironmentRevision
        )

        currentComputeEnvironment = "{ENV_ID}-{ENV_REVISION}".format(
            ENV_ID = computeEnvironmentRevision["id"],
            ENV_REVISION = computeEnvironmentRevision["revision"]
        )

        # Check if we already pulled this Compute Environment at the specific Revision
        if app.config["EXPORTS_PROJECT_FILES_FORCE_RUN"] or currentComputeEnvironment != savedComputeEnvironment:

        # Need to validate if this IF does what we expect
        #if app.config["EXPORTS_PROJECT_FILES_FORCE_RUN"] or !((computeEnvironmentRevision["id"] == priorExportedcomputeEnvironmentID) and (computeEnvironmentRevision["revision"] == priorExportedcomputeEnvironmentRevision)):

            #print("Starting Docker image export for {0}/{1} to {2}/{3}".format(dominoUsername, dominoProjectName, exportGroupName, exportProjectName))

            # Pull Docker image
            self.setExecutionStatus(StatusTypes.code["DockerExportImagePullStarted"])
            pulledDominoDockerImage = dockerClient.pull(computeEnvironmentURL)
            self.setExecutionStatus(StatusTypes.code["DockerExportImagePullEnded"])

            # Build Docker image
            # Define the Docker latest image URI
            # Note that we convert most of the variables here to lowercase, as
            #  defined on https://docs.docker.com/engine/reference/commandline/tag/#extended-description
            exportDockerImageLatestURL = app.config["EXPORTS_DOCKER_IMAGE_NAME_LATEST_FORMAT"].format(
                DOCKER_REGISTRY = app.config["EXPORTS_DOCKER_REGISTRY"],
                DOMINO_USERNAME = dominoUsername.lower(),
                DOMINO_PROJECT_NAME = dominoProjectName.lower(),
                EXPORT_GROUP_NAME = exportGroupName.lower(),
                EXPORT_PROJECT_NAME = exportProjectName.lower(),
                DOMINO_COMPUTE_ENVIRONMENT_ID = computeEnvironmentRevision["id"].lower(),
                DOMINO_COMPUTE_ENVIRONMENT_REVISION = computeEnvironmentRevision["revision"]
            )

            # Define the Docker specific version image URI
            exportDockerImageVersionURL = app.config["EXPORTS_DOCKER_IMAGE_NAME_VERSION_FORMAT"].format(
                DOCKER_REGISTRY = app.config["EXPORTS_DOCKER_REGISTRY"],
                DOMINO_USERNAME = dominoUsername.lower(),
                DOMINO_PROJECT_NAME = dominoProjectName.lower(),
                EXPORT_GROUP_NAME = exportGroupName.lower(),
                EXPORT_PROJECT_NAME = exportProjectName.lower(),
                DOMINO_COMPUTE_ENVIRONMENT_ID = computeEnvironmentRevision["id"].lower(),
                DOMINO_COMPUTE_ENVIRONMENT_REVISION = computeEnvironmentRevision["revision"]
            )

            self.setExecutionStatus(StatusTypes.code["DockerExportImageBuildStarted"])
            exportDockerImageBuildLatest = dockerClient.build(dockerFileTemplatePath, computeEnvironmentURL, exportDockerImageLatestURL)
            exportDockerImageBuildVersion = dockerClient.build(dockerFileTemplatePath, computeEnvironmentURL, exportDockerImageVersionURL)
            self.setExecutionStatus(StatusTypes.code["DockerExportImageBuildEnded"])

            # Clean up after build
            dockerClient.cleanup()

            # Push Docker Image to :latest :v{num}
            self.setExecutionStatus(StatusTypes.code["DockerExportImagePushStarted"])
            pushedDockerImageVersion = dockerClient.push(exportDockerImageVersionURL)
            pushedDockerImageLatest = dockerClient.push(exportDockerImageLatestURL)
            self.setExecutionStatus(StatusTypes.code["DockerExportImagePushEnded"])

            self.updateExecutionDetails(
                {
                    "exportedComputeEnvironment": {
                        "id": computeEnvironmentRevision["id"],
                        "revision": computeEnvironmentRevision["revision"],
                        "name": computeEnvironmentDetails["name"]
                    },
                    "exportedComputeEnvironmentURLs": {
                        "latest": exportDockerImageLatestURL,
                        "version": exportDockerImageVersionURL
                    }
                }
            )

            # Ensure we don't push the same image again in the future
            self.updateJobTaskStates(
                [
                    {
                        "task": "ProjectDockerImageExportTask",
                        "taskInfo": {
                            "lastCompletedExecutionID": self._execution.execution_id,
                            "computeEnvironmentID": computeEnvironmentRevision["id"],
                            "computeEnvironmentRevision": computeEnvironmentRevision["revision"]
                        }
                    },
                    {
                        "task": "ProjectExportReportToS3Task", 
                        "taskInfo": {
                            "statusSaved": False,
                        }
                    }
                ]
            )
            self.updateJobRun()
        else:
            #print("Skipping Docker image export for {0}/{1} to {2}/{3}".format(dominoUsername, dominoProjectName, exportGroupName, exportProjectName))
            taskStatus = StatusTypes.code["Skipped"]
            self.updateExecutionDetails(
                {
                    "exportedComputeEnvironment": {
                        "id": None,
                        "revision": None,
                        "name": None
                    },
                    "exportedComputeEnvironmentURLs": {
                        "latest": None,
                        "version": None
                    }
                }
            )
            self.updateJobRun(jobDetails.get("taskState", {}).get("ProjectDockerImageExportTask", {}).get("lastCompletedExecutionID", None))

        return taskStatus


class UpdateAllExportStatusS3Task(BaseExecution):
    @stopit.threading_timeoutable(default=StatusTypes.code["ExecutionRunTimeout"])
    def defaultTask(self):
        from app import app
        statusRecords = self._dbCommon.allProjectExportJobsStatus()
        exportsLogFilePath = DBHelpers.exportsLogFilePath()

        #print("Writing to {0}".format(exportsLogFilePath))

        with open(exportsLogFilePath, "w") as exportsLogFile:
            exportsLogFile.write(app.config["EXPORTS_PROJECT_FILES_S3_TOP_LEVEL_LOG_FORMATTER"](statusRecords))

        #print("Done writing to log file...")

class ProjectExportReportToS3Task(BaseExecution):
    @stopit.threading_timeoutable(default=StatusTypes.code["ExecutionRunTimeout"])
    def defaultTask(self):
        from app import app
        taskStatus = None

        jobDetails = json.loads(encrypter.decrypt(self._execution.jobs.job_details))

        if not jobDetails.get("taskState", {}).get("ProjectExportReportToS3Task", {}).get("statusSaved", False):
            # Do this first to ensure that self._dbCommon.projectExportStatusHistory() knows to display the status of the current job
            self.updateExecutionDetails({"statusSaved": True})
            self.updateJobRun()

            statusRecords = self._dbCommon.projectExportStatusHistory(self._execution.job_id, app.config["EXPORTS_PROJECT_FILES_S3_SYNC_LOG_MAX_RECORDS"])

            syncStatusLogFilePath = DBHelpers.syncLogFilePath(
                self._execution.jobs.job_user,
                self._execution.jobs.job_project,
                self._execution.jobs.job_export_group,
                self._execution.jobs.job_export_project
            )

            #print("Writing to {0}".format(syncStatusLogFilePath))

            with open(syncStatusLogFilePath, "w") as syncStatusLog:
                syncStatusLog.write(app.config["EXPORTS_PROJECT_FILES_S3_SYNC_LOG_FORMATTER"](statusRecords))

            #print("Done writing to log file...")
            self.updateJobTaskStates(
                [
                    {
                        "task": "ProjectExportReportToS3Task", 
                        "taskInfo": {
                            "lastCompletedExecutionID": self._execution.execution_id,
                            "statusSaved": True
                        }
                    }
                ]
            )
        else:
            self.updateExecutionDetails({"statusSaved": False})  
            self.updateJobRun(jobDetails.get("taskState", {}).get("ProjectExportReportToS3Task", {}).get("lastCompletedExecutionID", None))
            taskStatus = StatusTypes.code["Skipped"]

        return taskStatus

class HealthMetricsCollectionTask(BaseExecution):
    @stopit.threading_timeoutable(default=StatusTypes.code["ExecutionRunTimeout"])
    def defaultTask(self):
        from app.admin import HealthMetrics
        from app import app

        taskStatus = None

        healthMetrics = HealthMetrics()

        metrics = models.Metric(
            domino_api_healthy = healthMetrics.isDominoAPIHealthy(timeout = app.config["HEALTHCHECK_TIMEOUT_IN_SECONDS"]),
            domino_docker_registry_healthy = healthMetrics.isDominoDockerRegistryHealthy(timeout = app.config["HEALTHCHECK_TIMEOUT_IN_SECONDS"]),
            external_docker_registry_healthy = healthMetrics.isExternalDockerRegistryHealthy(timeout = app.config["HEALTHCHECK_TIMEOUT_IN_SECONDS"]),
            external_s3_bucket_healthy = healthMetrics.isS3BucketHealthy(timeout = app.config["HEALTHCHECK_TIMEOUT_IN_SECONDS"])
        )

        self._dbSession.add(metrics)
        self._dbSession.commit()

        return taskStatus

class DatabasePruneTask(BaseExecution):
    @stopit.threading_timeoutable(default=StatusTypes.code["ExecutionRunTimeout"])
    def defaultTask(self):
        from app.admin import Cleanup
        from app import app

        taskStatus = None

        cleanup = Cleanup(self._dbSession)
        cleanup.pruneMetrics()
        cleanup.pruneExecutions()

        return taskStatus

class ProjectExportJob(BaseJob):
    def __init__(self, jobID, scheduler):
        super().__init__(jobID, scheduler)

        if not self.isJobAlreadyRunning():
            projectExportRunTasks = ["ProjectFilesExportTask", "ProjectDockerImageExportTask"]
            self.addSubTasks(projectExportRunTasks)
            self.run()
            self.wait()

            # Report to S3
            projectExportReportingTasks = ["ProjectExportReportToS3Task"]
            self.addSubTasks(projectExportReportingTasks)
            self.run()
            self.wait()
        else:
            self._logger.info("Skipping ProjectExport job ({0}) because it is already running".format(self._job.export_id))

class HealthMetricsCollectionJob(BaseJob):
    def __init__(self, jobID, scheduler):
        super().__init__(jobID, scheduler)

        if not self.isJobAlreadyRunning():
            runTasks = ["HealthMetricsCollectionTask"]
            self.addSubTasks(runTasks)
            self.run()
            self.wait()
        else:
            self._logger.info("Skipping HealthMetricsCollection job ({0}) because it is already running".format(self._job.export_id))

class UpdateAllExportStatusS3Job(BaseJob):
    def __init__(self, jobID, scheduler):
        super().__init__(jobID, scheduler)

        if not self.isJobAlreadyRunning():
            runTasks = ["UpdateAllExportStatusS3Task"]
            self.addSubTasks(runTasks)
            self.run()
            self.wait()
        else:
            self._logger.info("Skipping UpdateAllExportStatusS3 job ({0}) because it is already running".format(self._job.export_id))

class DatabasePruneJob(BaseJob):
    def __init__(self, jobID, scheduler):
        super().__init__(jobID, scheduler)

        if not self.isJobAlreadyRunning():
            runTasks = ["DatabasePruneTask"]
            self.addSubTasks(runTasks)
            self.run()
            self.wait()
        else:
            self._logger.info("Skipping DatabasePrune job ({0}) because it is already running".format(self._job.export_id))