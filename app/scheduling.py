from app import db
from app.dbcommon import DBCommon
import app.jobs as Jobs
from app.status import StatusTypes

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ProcessPoolExecutor
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from pytz import utc
from datetime import datetime, timedelta, timezone

class Scheduler(object):
    def __init__(self,):
        self.__scheduler = BackgroundScheduler()
        self.__dbSession = None
        self.__dbCommon = None
        self.__runningJobs = []
        self.__jobTypes = {
            "ProjectExport": Jobs.ProjectExportJob,
            "AllExportJobsS3Status": Jobs.UpdateAllExportStatusS3Job,
            "HealthMetricsCollection": Jobs.HealthMetricsCollectionJob,
            "DatabasePrune": Jobs.DatabasePruneJob
        }
        self.__executionTypes = {
            "ProjectFilesExportTask": Jobs.ProjectFilesExportTask,
            "ProjectDockerImageExportTask": Jobs.ProjectDockerImageExportTask,
            "ProjectExportReportToS3Task": Jobs.ProjectExportReportToS3Task,
            "UpdateAllExportStatusS3Task": Jobs.UpdateAllExportStatusS3Task,
            "HealthMetricsCollectionTask": Jobs.HealthMetricsCollectionTask,
            "DatabasePruneTask": Jobs.DatabasePruneTask
        }

    def start(self, workerType = "thread", maxWorkers = 10, timezone = utc):
        self.__dbSession = db.dbSession
        self.__dbCommon = DBCommon(self.__dbSession)

        if maxWorkers < 3:
            maxWorkers = 3

        executors = {
            "default": {
                "type": "threadpool",
                "max_workers": maxWorkers
            },
            "jobs": {
                "type": "threadpool",
                "max_workers": maxWorkers
            },
            "executions": {
                "type": "threadpool",
                "max_workers": maxWorkers * 3
            }
        }

        job_defaults = {
            "coalesce": True,
            "max_instances": 1
        }

        self.__scheduler.configure(executors=executors, job_defaults=job_defaults, timezone=timezone)
        self.__scheduler.start()
        self.refreshJobs()

        #self.__scheduler.print_jobs()

    def refreshJobs(self):
        self.__scheduler.remove_all_jobs();

        for job in self.__dbCommon.getAllJobs():
            self.addJob(jobID=job.job_id, runNow=False)


    def updateJob(self, jobID):
        job = self.__dbCommon.getJob(jobID)

        if job.export_id in self.__runningJobs:
            # This should allow us to refresh the job
            # APScheduler will allow any prior, running jobs to complete without
            #  killing them when we remove the job from the scheduler
            self.__scheduler.remove_job(job.export_id)
            # Newly add the job with the new details
            self.addJob(job.job_id)


    def addJob(self, jobID, runNow = True):
# Think about adding a try; except clause here to not crash the server if there is an issue
        job = self.__dbCommon.getJob(jobID)
        nowTrigger = DateTrigger(run_date = datetime.now(tz=timezone.utc))
        scheduledTrigger = IntervalTrigger(seconds = job.run_frequency_seconds)

        scheduledJob = None

        jobRunner = self.__jobTypes.get(job.job_type, Jobs.BaseJob)

        if runNow:
            nowJob = self.__scheduler.add_job(
                func = jobRunner,
                args = [job.job_id, self],
                id = None,
                executor = "jobs",
                misfire_grace_time = 60,
                trigger = nowTrigger
            )
            #print("Added Project Export Job {0} with export_id {1} as now {2} trigger".format(job, job.export_id, type(nowTrigger)))

        scheduledJob = self.__scheduler.add_job(
            func = jobRunner,
            args = [job.job_id, self],
            id = job.export_id,
            executor = "jobs",
            misfire_grace_time = 60,
            trigger = scheduledTrigger,
            jitter = 300
        )

        #print("Added Job {0} with export_id {1} as interval {2} trigger".format(job, job.export_id, type(scheduledTrigger)))

        self.__runningJobs.append(job.export_id)

        return scheduledJob

    def removeJob(self, jobID):
        try:
            job = self.__dbCommon.getJob(jobID)
            if job:
                self.__scheduler.remove_job(job.export_id)
        except:
            pass

    def removeExecution(self, executionID, statusCode = None):
        try:
            execution = self.__dbCommon.getExecution(executionID)
            if execution:
                if statusCode:
                    execution.execution_status = statusCode
                self.__scheduler.remove_job(execution.external_execution_id)
        except:
            pass

    def addExecution(self, executionID):
# Think about adding a try; except clause here to not crash the server if there is an issue
        execution = self.__dbCommon.getExecution(executionID)

        now = datetime.now(tz=timezone.utc)
        nowTrigger = DateTrigger(run_date = now)

        scheduledJob = self.__scheduler.add_job(
            func = self.__executionTypes.get(execution.execution_type, Jobs.BaseExecution),
            args = [execution.execution_id, self],
            id = execution.external_execution_id,
            executor = "executions",
            trigger = nowTrigger
        )

        #print("Added Execution with export_id {0} as '{1}' trigger".format(execution.external_execution_id, now))

        return scheduledJob