import app
import app.models as models
from app.helpers import DBHelpers
from app.status import StatusTypes

from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy import and_
from sqlite3 import OperationalError
from sqlalchemy.exc import InvalidRequestError
from time import sleep
import json

class DBError(Exception):
    pass

class DBExportJobExists(DBError):
    pass

class DBProjectJobExists(DBError):
    pass

class DBExportJobDoesNotExist(DBError):
    pass

class DBCommon(object):
    def __init__(self, dbSession):
        self.__dbSession = dbSession

    def query(self, *entities, **kwargs):
        request = None
        attempt = 0
        while True:
            try:
                request = self.__dbSession.query(*entities, **kwargs)
                break
            except (OperationalError, InvalidRequestError):
                if attempt < app.config["SQLALCHEMY_MAX_QUERY_ATTEMPTS"]:
                    attempt += 1
                    sleep(app.config["SQLALCHEMY_MAX_QUERY_ATTEMPTS_WAIT_SECONDS"])
                    continue
                else:
                    raise

        return request

    def raiseOnJobExists(self, username, projectName, exportGroupName, exportProjectName, skipProjectCheck = False):
        if not skipProjectCheck and self.query(models.Job).filter(and_(
            models.Job.job_user == username,
            models.Job.job_project == projectName
        )).first() is not None:
            raise(DBProjectJobExists)
        elif self.query(models.Job).filter(and_(
            models.Job.job_export_group == exportGroupName,
            models.Job.job_export_project == exportProjectName
        )).first() is not None:
            raise(DBExportJobExists)

    def getJob(self, jobID):
        return self.query(models.Job).filter(models.Job.job_id == jobID).first()

    def getJobByExportID(self, exportID):
        return self.query(models.Job).filter(models.Job.export_id == exportID).first()

    def getJobRun(self, jobID, jobRunID, executionType):
        return self.query(models.JobRun).filter(and_(
            models.JobRun.job_id == jobID,
            models.JobRun.job_run_id == jobRunID,
            models.JobRun.execution_type == executionType
        )).first()

    def getAllJobs(self):
        return self.query(models.Job).all()

    def getAllRunningExecutions(self):
        return self.query(models.Execution).filter(and_(
            models.Execution.execution_status > StatusTypes.code["Initializing"],
            models.Execution.execution_status != StatusTypes.code["Completed"]
        )).all()

    def getAllProjectExportJobs(self):
        return self.query(models.Job).filter(models.Job.job_type == "ProjectExport").all()

    def getServicesJobs(self, jobType = None):
        serviceJobTypes = ["AllExportJobsS3Status", "HealthMetricsCollection", "DatabasePrune"]

        jobs = []
        if jobType and (jobType in serviceJobTypes):
            jobs = self.query(models.Job).filter(models.Job.job_type == jobType).all()
        else:
            jobs = self.query(models.Job).filter(models.Job.job_type.in_(serviceJobTypes)).all()

        return jobs

    def getLatestHealthMetrics(self):
        return self.query(models.Metric).order_by(models.Metric.collection_timestamp.desc()).limit(1).first()

    def getExecution(self, executionID):
        return self.query(models.Execution).filter(models.Execution.execution_id == executionID).first()

    def getRunningExecutionsForJobRun(self, jobID, jobRunID):
        return self.query(models.Execution).filter(and_(
            models.Execution.job_id == jobID,
            models.Execution.job_run_id == jobRunID,
            models.Execution.execution_status > StatusTypes.code["Initializing"],
            models.Execution.execution_status != StatusTypes.code["Completed"],
            models.Execution.execution_ended_timestamp == None
        )).all()

    def getNextJobRunID(self, jobID):
        return self.getLastJobRunID(jobID) + 1

    def getLastJobRunID(self, jobID):
        maxRun = 0
        lastJobRun = self.query(models.JobRun).filter(models.JobRun.job_id == jobID).order_by(models.JobRun.job_run_id.desc()).limit(1).first()
        if lastJobRun:
            maxRun = lastJobRun.job_run_id

        return maxRun

    def getJobRunByExecutionIDs(self, executionIDs):
        return self.query(models.JobRun).filter(
            models.JobRun.associated_execution_id.in_(executionIDs)
        )

    def getAllMetricsPriorToDatetime(self, datetime):
        return self.query(models.Metric).filter(
            models.Metric.collection_timestamp < datetime
        )

    def getAllExecutionsPriorToDatetime(self, datetime):
        return self.query(models.Execution).filter(
            models.Execution.execution_started_timestamp < datetime
        )

    def isJobRunning(self, jobID):
        return self.query(models.Execution).filter(and_(
            models.Execution.job_id == jobID,
            models.Execution.execution_status > StatusTypes.code["Initializing"],
            models.Execution.execution_status != StatusTypes.code["Completed"],
            models.Execution.execution_ended_timestamp == None
        )).first() is not None

    def projectExportStatusHistory(self, jobID, maxRecords, showSkipped = False):
        statusRecords = []

        jobRunID = self.getLastJobRunID(jobID)
        recordsCount = 0

        while (recordsCount < maxRecords) and (jobRunID > 0):
            status = self.projectExportStatusByJobIDRun(jobID, jobRunID)
            if (showSkipped) or (status["status"] != "skipped"):
                statusRecords.append(status)
                recordsCount = recordsCount + 1

            jobRunID = jobRunID - 1

        return statusRecords

    def allProjectExportJobsStatus(self, showOnly = ["scheduled", "success", "error", "disabled"]):
        statusRecords = []

        for job in self.getAllProjectExportJobs():
            jobID = job.job_id
            jobRunID = self.getLastJobRunID(jobID)

            while jobRunID > 0:
                status = self.projectExportStatusByJobIDRun(jobID, jobRunID)

                if status["status"] in showOnly:
                    break

                jobRunID = jobRunID - 1

            statusSubsetData = {
                "timestamp": status["timestamp"],
                "export_id": status["export_id"],
                "status": status["status"],
                "sync_log_path": DBHelpers.syncLogFilePath(
                    status["domino_username"],
                    status["domino_project_name"],
                    status["export_group_name"],
                    status["export_project_name"]
                ) if status["status"] != "scheduled" else None
            }

            statusRecords.append(statusSubsetData)

        return statusRecords

    def projectExportStatusLastHistory(self, jobID):
        jobRunID = self.getLastJobRunID(jobID)
        status = self.projectExportStatusByJobIDRun(jobID, jobRunID)

        return status

    def executionsAreRunning(self, executions):
        running = False

        for execution in executions:
            if execution and execution.execution_status >= StatusTypes.code["Running"]:
                running = True
                break

        return running

    def executionsAreSkipped(self, executions):
        skipped = True

        for execution in executions:
            if execution:
                if execution.execution_status == StatusTypes.code["Skipped"]:
                    skipped = skipped and True
                else:
                    skipped = skipped and False
            else:
                # Do not skip if execution does not exist
                skipped = skipped and False

        return skipped

    def executionsHaveErrors(self, executions):
        error = False

        for execution in executions:
            if execution and execution.execution_status <= StatusTypes.code["UnknownError"]:
                error = True
                break

        return error

    def executionsAreDisabled(self, executions):
        disabled = False

        for execution in executions:
            if execution and execution.execution_status == StatusTypes.code["Disabled"]:
                disabled = True
                break

        return disabled

    def projectExportStatusByJobIDRun(self, jobID, jobRunID):
        job = self.getJob(jobID)

        if not job:
            status = {}
        else:
            jobDetails = json.loads(app.encrypter.decrypt(job.job_details))

            status = {
                "timestamp": job.job_updated_timestamp,
                "export_id": job.export_id,
                "status": None,
                "error_code": 0,
                "error_message": None,
                "export_frequency_seconds": job.run_frequency_seconds,
                "domino_username": job.job_user,
                "domino_project_name": job.job_project,
                "export_group_name": job.job_export_group,
                "export_project_name": job.job_export_project,
                "project_export_runtime_seconds": 0,
                "project_export_location": None,
                "project_commit_id": None,
                "project_export_status": None,
                "image_export_runtime_seconds": 0,
                "image_export_location": [],
                "image_export_status": None,
                "domino_image_environment_name": None
            }

            if (type(jobRunID) == int) and (jobRunID == 0):
                status["status"] = "scheduled"
            elif (type(jobRunID) == int) and (jobRunID > 0):
                # ProjectExportReportToS3Task
                jobRunProjectExportReportToS3Task = self.getJobRun(jobID, jobRunID, "ProjectExportReportToS3Task")
                # ProjectFilesExportTask
                jobRunProjectFilesExportTask = self.getJobRun(jobID, jobRunID, "ProjectFilesExportTask")
                jobRunProjectFilesExportTaskExecution = self.getExecution(jobRunProjectFilesExportTask.associated_execution_id) if jobRunProjectFilesExportTask else None
                # ProjectDockerImageExportTask
                jobRunProjectDockerImageExportTask = self.getJobRun(jobID, jobRunID, "ProjectDockerImageExportTask")
                jobRunProjectDockerImageExportTaskExecution = self.getExecution(jobRunProjectDockerImageExportTask.associated_execution_id) if jobRunProjectDockerImageExportTask else None

                if jobRunProjectFilesExportTaskExecution:
                    status["project_export_status"] = StatusTypes.type[jobRunProjectFilesExportTaskExecution.execution_status]
                if jobRunProjectDockerImageExportTaskExecution:
                    status["image_export_status"] = StatusTypes.type[jobRunProjectDockerImageExportTaskExecution.execution_status]

                executions = (jobRunProjectFilesExportTaskExecution, jobRunProjectDockerImageExportTaskExecution)
                if self.executionsAreRunning(executions):
                    status["status"] = "running"
                elif self.executionsHaveErrors(executions):
                    status["status"] = "error"
                    for e in executions:
                        if e.execution_status <= StatusTypes.code["UnknownError"]:
                            exceptionDetails = {}
                            if e.execution_details:
                                executionDetails = json.loads(app.encrypter.decrypt(e.execution_details))
                                exceptionDetails = executionDetails.get("exception", {})
                            status["error_code"] = e.execution_status
                            status["error_message"] = StatusTypes.message[status["error_code"]].format(**exceptionDetails)
                            break
                else:
                    if self.executionsAreSkipped(executions):
                        status["status"] = "skipped"
                    elif self.executionsAreDisabled(executions):
                        status["status"] = "disabled"
                    else:
                        status["status"] = "success"

                    if jobRunProjectFilesExportTask:
                        if jobRunProjectFilesExportTask.associated_execution_id != jobRunProjectFilesExportTask.last_successful_execution_id:
                            jobRunProjectFilesExportTaskExecution = self.getExecution(jobRunProjectFilesExportTask.last_successful_execution_id)
                        else:
                            # Only capture runtime if we ran this task during this export execution, otherwise keep the runtime as 0
                            status["project_export_runtime_seconds"] = (jobRunProjectFilesExportTaskExecution.execution_ended_timestamp - jobRunProjectFilesExportTaskExecution.execution_started_timestamp).total_seconds()

                        if jobRunProjectFilesExportTaskExecution:
                            # We always want to grab the task details, even if we did not execute the task during this export execution
                            projectFilesExportDetails = json.loads(app.encrypter.decrypt(jobRunProjectFilesExportTaskExecution.execution_details))
                            if projectFilesExportDetails:
                                status["project_export_location"] = projectFilesExportDetails["S3Paths"]["latest"]
                                status["project_commit_id"] = projectFilesExportDetails["commitID"]

                    if jobRunProjectDockerImageExportTask:
                        if jobRunProjectDockerImageExportTask.associated_execution_id != jobRunProjectDockerImageExportTask.last_successful_execution_id:
                            jobRunProjectDockerImageExportTaskExecution = self.getExecution(jobRunProjectDockerImageExportTask.last_successful_execution_id)
                        else:
                            # Only capture runtime if we ran this task during this export execution, otherwise keep the runtime as 0
                            status["image_export_runtime_seconds"] = (jobRunProjectDockerImageExportTaskExecution.execution_ended_timestamp - jobRunProjectDockerImageExportTaskExecution.execution_started_timestamp).total_seconds()

                        if jobRunProjectDockerImageExportTaskExecution:
                            # We always want to grab the task details, even if we did not execute the task during this export execution
                            projectDockerImageExportDetails = json.loads(app.encrypter.decrypt(jobRunProjectDockerImageExportTaskExecution.execution_details))
                            if projectDockerImageExportDetails:
                                status["image_export_location"] = [
                                    projectDockerImageExportDetails["exportedComputeEnvironmentURLs"]["latest"],
                                    projectDockerImageExportDetails["exportedComputeEnvironmentURLs"]["version"]
                                ]
                                imageOutputFormat = "{COMPUTE_ENVIRONMENT_NAME} v{COMPUTE_ENVIRONMENT_REVISION} [{COMPUTE_ENVIRONMENT_ID}]"
                                status["domino_image_environment_name"] = imageOutputFormat.format(
                                    COMPUTE_ENVIRONMENT_NAME = projectDockerImageExportDetails["exportedComputeEnvironment"]["name"],
                                    COMPUTE_ENVIRONMENT_ID = projectDockerImageExportDetails["exportedComputeEnvironment"]["id"],
                                    COMPUTE_ENVIRONMENT_REVISION = projectDockerImageExportDetails["exportedComputeEnvironment"]["revision"]
                                )

                times = []
                if jobRunProjectFilesExportTask:
                    times.append(jobRunProjectFilesExportTask.job_run_started_timestamp)
                if jobRunProjectDockerImageExportTask:
                    times.append(jobRunProjectDockerImageExportTask.job_run_started_timestamp)
                if jobRunProjectExportReportToS3Task:
                    times.append(jobRunProjectExportReportToS3Task.job_run_started_timestamp)
                status["timestamp"] = min([ts for ts in times if ts])
            else:
                status["status"] = "error"
                status["error_code"] = StatusTypes.code["InvalidJobRunID"]
                status["error_message"] = StatusTypes.messageFromType["InvalidJobRunID"]
        return status