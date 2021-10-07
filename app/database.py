from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import event
from sqlalchemy.engine import Engine
import time
import logging

class Database(object):
    def __init__(self):
        self.engine = None
        self.dbSession = None
        self.Base = declarative_base()

    def __set_sqlite_pragma(self, dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    def start(self, databaseURI):
        from app import app

        self.engine = create_engine(databaseURI, convert_unicode=True, connect_args={"timeout": 30})
        self.dbSession = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=self.engine))
        self.Base.query = self.dbSession.query_property()

        event.listen(self.engine, 'connect', self.__set_sqlite_pragma)

    def initDB(self):
        # import all modules here that might define models so that
        # they will be registered properly on the metadata.  Otherwise
        # you will have to import them first before calling init_db()
        import app.models
        self.Base.metadata.create_all(bind=self.engine)

    def updateServiceJobs(self):
        from app.dbcommon import DBCommon
        import app.models as models
        from app import app
        dbcommon = DBCommon(self.dbSession)

        # Check if no jobs scheduled
        s3ExportJobs = dbcommon.getServicesJobs("AllExportJobsS3Status")
        if not s3ExportJobs:
            job = models.Job(
                job_type = "AllExportJobsS3Status",
                job_user = None,
                job_project = None,
                job_export_group = None,
                job_export_project = None,
                run_frequency_seconds = app.config["EXPORTS_PROJECT_FILES_S3_TOP_LEVEL_LOG_FREQUENCY_SECONDS"],
                job_secrets = None,
                job_details = ""
            )
            self.dbSession.add(job)
            self.dbSession.commit()
        else:
            for job in s3ExportJobs:
                job.run_frequency_seconds = app.config["EXPORTS_PROJECT_FILES_S3_TOP_LEVEL_LOG_FREQUENCY_SECONDS"]
                self.dbSession.commit()

        metricsCollectionJobs = dbcommon.getServicesJobs("HealthMetricsCollection")
        if not metricsCollectionJobs:
            job = models.Job(
                job_type = "HealthMetricsCollection",
                job_user = None,
                job_project = None,
                job_export_group = None,
                job_export_project = None,
                run_frequency_seconds = app.config["HEALTHCHECK_SCHEDULE_FREQUENCY_SECONDS"],
                job_secrets = None,
                job_details = ""
            )
            self.dbSession.add(job)
            self.dbSession.commit()
        else:
            for job in metricsCollectionJobs:
                job.run_frequency_seconds = app.config["HEALTHCHECK_SCHEDULE_FREQUENCY_SECONDS"]
                self.dbSession.commit()

        databasePruneJobs = dbcommon.getServicesJobs("DatabasePrune")
        if not databasePruneJobs:
            job = models.Job(
                job_type = "DatabasePrune",
                job_user = None,
                job_project = None,
                job_export_group = None,
                job_export_project = None,
                run_frequency_seconds = app.config["DATABASE_PRUNE_FREQUENCY_SECONDS"],
                job_secrets = None,
                job_details = ""
            )
            self.dbSession.add(job)
            self.dbSession.commit()
        else:
            for job in databasePruneJobs:
                job.run_frequency_seconds = app.config["DATABASE_PRUNE_FREQUENCY_SECONDS"]
                self.dbSession.commit()


    def updateProjectJobs(self):
        from app.dbcommon import DBCommon
        from app import app
        dbcommon = DBCommon(self.dbSession)

        projectJobs = dbcommon.getAllProjectExportJobs()
        for job in projectJobs:
            job.run_frequency_seconds = app.config["EXPORT_JOB_SCHEDULE_DEFAULT_FREQUENCY_SECONDS"]
            self.dbSession.commit()

    def updateExecutions(self):
        from app.dbcommon import DBCommon
        from app.status import StatusTypes
        dbcommon = DBCommon(self.dbSession)

        executions = dbcommon.getAllRunningExecutions()
        for execution in executions:
            execution.execution_status = StatusTypes.code["ExecutionNotComplete"]
            self.dbSession.commit()

    def close(self):
        if self.engine:
            self.engine.dispose()

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement,
                        parameters, context, executemany):
    conn.info.setdefault('query_start_time', []).append(time.time())

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement,
                        parameters, context, executemany):
    logger = logging.getLogger(__name__)
    total = time.time() - conn.info['query_start_time'].pop(-1)
    logger.debug("Query [{1:f} seconds]: {0}".format(
        statement.replace('\n', ' '),
        total
    ))
