from app import app
from app import scheduler
from app import encrypter
import app.models as models
from app.dbcommon import DBCommon
from app.dbcommon import DBExportJobExists, DBExportJobDoesNotExist, DBProjectJobExists
from app.status import StatusTypes
from domino import DominoAPISession
from domino import DominoAPIKeyInvalid, DominoAPIUnauthorized, DominoAPINotFound, DominoAPIBadRequest, DominoAPIComputeEnvironmentRevisionNotAvailable, DominoAPIUnexpectedError

from werkzeug.exceptions import BadRequest
import json
import re

class ExportAPIError(Exception):
    pass

class ExportAPIInvalidExportGroupName(ExportAPIError):
    pass

class ExportAPIInvalidExportProjectName(ExportAPIError):
    pass

class ProjectsAPI(object):
    def __init__(self, dominoAPIKey, dbSession):
        self.dominoAPIKey = dominoAPIKey
        self.dbSession = dbSession
        self.dbCommon = DBCommon(self.dbSession)
        self.dominoAPI = DominoAPISession(app.config["DOMINO_API_SERVER"], self.dominoAPIKey, verifySSL = app.config["DOMINO_API_SERVER_VERIFY_SSL"])
        self.reDockerRegistryName = re.compile("^[a-z0-9]+(?:[._-]{1,2}[a-z0-9]+)*$")

    def create(self, username, projectName, exportGroupName, exportProjectName):
        respCode = 201
        jobData = {
            "success": None,
            "message": None,
            "export_id": None,
            "export_frequency_seconds": None
        }

        try:
            if not self.dominoAPI.isValidAPIKey():
                raise(DominoAPIKeyInvalid)

            jobType = "ProjectExport"
            jobRunFrequencyInSeconds = app.config["EXPORT_JOB_SCHEDULE_DEFAULT_FREQUENCY_SECONDS"]

            # Expect to get Exceptions here if the Domino API Key does not provide access to the Project
            projectInfo = self.dominoAPI.findProjectByOwnerAndName(username, projectName)
            if not self.dominoAPI.hasAccessToProject(username, projectName):
                raise(DominoAPIUnauthorized)

            # Check export group and project names for compliance with Docker Registry naming requirements
            if not self.reDockerRegistryName.match(exportGroupName):
                if self.reDockerRegistryName.match(exportGroupName.lower()):
                    exportGroupName = exportGroupName.lower()

                    jobMessageFormat = "{MESSAGE}"
                    if jobData["message"]:
                        jobMessageFormat = "{ORIGINAL};  {MESSAGE}"

                    jobData["message"] = jobMessageFormat.format(
                        ORIGINAL = jobData["message"],
                        MESSAGE = "Warning: request has been processed, but the Export Group Name has been automatically converted to lower case to comply with Docker Registry standards"
                    )
                else:
                    raise(ExportAPIInvalidExportGroupName)

            if not self.reDockerRegistryName.match(exportProjectName):
                if self.reDockerRegistryName.match(exportProjectName.lower()):
                    exportProjectName = exportProjectName.lower()

                    jobMessageFormat = "{MESSAGE}"
                    if jobData["message"]:
                        jobMessageFormat = "{ORIGINAL};  {MESSAGE}"

                    jobData["message"] = jobMessageFormat.format(
                        ORIGINAL = jobData["message"],
                        MESSAGE = "Warning: request has been processed, but the Export Project Name has been automatically converted to lower case to comply with Docker Registry standards"
                    )
                else:
                    raise(ExportAPIInvalidExportProjectName)

            # Expect to get Exceptions here if the job already exists
            self.dbCommon.raiseOnJobExists(username, projectName, exportGroupName, exportProjectName, app.config.get("ALLOW_SAME_PROJECT_EXPORTS", False))

            # Do the actual work here
            jobDetails = {
                    "taskState": {
                        "ProjectFilesExportTask": {
                            "lastCompletedExecutionID": None,
                            "commitID": None
                        },
                        "ProjectDockerImageExportTask": {
                            "lastCompletedExecutionID": None,
                            "computeEnvironmentID": None,
                            "computeEnvironmentRevision": None
                        },
                        "ProjectExportReportToS3Task": {
                            "lastCompletedExecutionID": None,
                            "statusSaved": False
                        }
                    },
                    "dockerBuildTemplateFile": "Standard.Dockerfile"
            }
            job = models.Job(
                job_type = jobType,
                job_user = username.lower(),
                job_project = projectName,
                job_export_group = exportGroupName,
                job_export_project = exportProjectName,
                run_frequency_seconds = jobRunFrequencyInSeconds,
                job_secrets = encrypter.encrypt(self.dominoAPIKey),
                job_details = encrypter.encrypt(json.dumps(jobDetails))
            )

            self.dbSession.add(job)
            self.dbSession.commit()

            jobData["success"] = True
            jobData["export_id"] = job.export_id
            jobData["export_frequency_seconds"] = job.run_frequency_seconds

            # Schedule job with scheduler
            scheduler.addJob(job.job_id, True)

        except BadRequest:
            respCode = 400
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIMalformedJSON"]
        except DominoAPINotFound:
            respCode = 400
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIProjectNotExist"]
        except (DominoAPIKeyInvalid, DominoAPIUnauthorized):
            respCode = 401
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIProjectNoAccess"]
        except DBExportJobExists:
            respCode = 409
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIExportNameConflict"]
        except DBProjectJobExists:
            respCode = 409
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIDominoNameConflict"]
        except ExportAPIInvalidExportGroupName:
            respCode = 422
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIInvalidExportGroupName"]
        except ExportAPIInvalidExportProjectName:
            respCode = 422
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIInvalidExportProjectName"]
        except (DominoAPIUnexpectedError, Exception) as e:
            respCode = 503
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["UnknownError"].format(repr(e))
            raise(e)

        return (respCode, jobData)
    
    def update(self, identity, updateAPIKey, exportGroupName, exportProjectName, disabled):
        respCode = 200
        jobData = {
            "success": None,
            "message": None,
            "export_id": None,
            "export_frequency_seconds": None
        }

        try:
            if not self.dominoAPI.isValidAPIKey():
                raise(DominoAPIKeyInvalid)

            job = self.dbCommon.getJobByExportID(identity)

            if not job:
                raise(DBExportJobDoesNotExist)
            # Expect to get Exceptions here if the Domino API Key does not provide access to the Project
            projectInfo = self.dominoAPI.findProjectByOwnerAndName(job.job_user, job.job_project)
            if not self.dominoAPI.hasAccessToProject(job.job_user, job.job_project):
                raise(DominoAPIUnauthorized)

            if updateAPIKey:
                job.job_secrets = encrypter.encrypt(self.dominoAPIKey)

            if exportGroupName:
                # Check export group name for compliance with Docker Registry naming requirements
                if not self.reDockerRegistryName.match(exportGroupName):
                    if self.reDockerRegistryName.match(exportGroupName.lower()):
                        exportGroupName = exportGroupName.lower()

                        jobMessageFormat = "{MESSAGE}"
                        if jobData["message"]:
                            jobMessageFormat = "{ORIGINAL};  {MESSAGE}"

                        jobData["message"] = jobMessageFormat.format(
                            ORIGINAL = jobData["message"],
                            MESSAGE = "Warning: request has been processed, but the Export Group Name has been automatically converted to lower case to comply with Docker Registry standards"
                        )
                    else:
                        raise(ExportAPIInvalidExportGroupName)

                job.job_export_group = exportGroupName
            if exportProjectName:
                # Check export project name for compliance with Docker Registry naming requirements
                if not self.reDockerRegistryName.match(exportProjectName):
                    if self.reDockerRegistryName.match(exportProjectName.lower()):
                        exportProjectName = exportProjectName.lower()

                        jobMessageFormat = "{MESSAGE}"
                        if jobData["message"]:
                            jobMessageFormat = "{ORIGINAL};  {MESSAGE}"

                        jobData["message"] = jobMessageFormat.format(
                            ORIGINAL = jobData["message"],
                            MESSAGE = "Warning: request has been processed, but the Export Project Name has been automatically converted to lower case to comply with Docker Registry standards"
                        )
                    else:
                        raise(ExportAPIInvalidExportProjectName)

                job.job_export_project = exportProjectName
            if type(disabled) == bool:
                job.job_active = (not disabled)

            if exportGroupName or exportProjectName:
                # Force project file and Docker image export tasks to run during next schedule
                jobDetails = json.loads(encrypter.decrypt(job.job_details))
                taskState = jobDetails.get("taskState", {})
                taskState["ProjectFilesExportTask"]["commitID"] = None
                taskState["ProjectDockerImageExportTask"]["computeEnvironmentID"] = None
                taskState["ProjectDockerImageExportTask"]["computeEnvironmentRevision"] = None
                jobDetails["taskState"] = taskState
                job.job_details = encrypter.encrypt(json.dumps(jobDetails))

            self.dbSession.commit()

            jobData["success"] = True
            jobData["export_id"] = job.export_id
            jobData["export_frequency_seconds"] = job.run_frequency_seconds

        except BadRequest:
            respCode = 400
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIMalformedJSON"]
        except DominoAPINotFound:
            respCode = 400
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIProjectNotExist"]
        except (DominoAPIKeyInvalid, DominoAPIUnauthorized):
            respCode = 401
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIProjectNoAccess"]
        except DBExportJobDoesNotExist:
            respCode = 404
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIExportIDNotExist"]
        except ExportAPIInvalidExportGroupName:
            respCode = 422
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIInvalidExportGroupName"]
        except ExportAPIInvalidExportProjectName:
            respCode = 422
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["ExportAPIInvalidExportProjectName"]
        except (DominoAPIUnexpectedError, Exception) as e:
            respCode = 503
            jobData["success"] = False
            jobData["message"] = StatusTypes.messageFromType["UnknownError"].format(repr(e))

        return (respCode, jobData)


    def status(self, identity = None, projectName = None):
        respCode = 200
        jobData = []

        try:
            if not self.dominoAPI.isValidAPIKey():
                raise(DominoAPIKeyInvalid)

            userJobs = []
            jobs = self.dbCommon.getAllProjectExportJobs()
            for job in jobs:
                if self.dominoAPI.hasAccessToProject(job.job_user, job.job_project):
                    userJobs.append(job)

            for userJob in userJobs:
                if identity:
                    if projectName:
                        # Status by userName and projectName
                        if (userJob.job_user == identity.lower()) and (userJob.job_project == projectName):
                            jobData = self.dbCommon.projectExportStatusHistory(userJob.job_id, app.config.get("API_STATUS_LOG_MAX_RECORDS", 10), True)
                    else:
                        # Status by export_id
                        if userJob.export_id == identity.lower():
                            jobData = self.dbCommon.projectExportStatusHistory(userJob.job_id, app.config.get("API_STATUS_LOG_MAX_RECORDS", 10), True)
                            break
                        # Status by userName
                        elif userJob.job_user == identity.lower():
                            status = self.dbCommon.projectExportStatusLastHistory(userJob.job_id)
                            if status:
                                jobData.append(status)
                # Status for all jobs
                else:
                    status = self.dbCommon.projectExportStatusLastHistory(userJob.job_id)
                    if status:
                        jobData.append(status)

        except DominoAPIKeyInvalid:
            respCode = 401
        except (DominoAPIUnexpectedError, Exception) as e:
            respCode = 503
            raise(e)

        return (respCode, jobData)
