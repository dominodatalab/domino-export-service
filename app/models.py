from app import db
from app.helpers import DBHelpers
from app.status import StatusTypes

from time import time
from sqlalchemy import Column, Integer, Boolean, String, JSON, DateTime, ForeignKey
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func

class Job(db.Base):
    __tablename__ = "jobs"
    job_id = Column(Integer, primary_key=True)
    export_id = Column(String, nullable=False, unique=True)
    job_type = Column(String, nullable=False)
    job_user = Column(String, nullable=True)
    job_project = Column(String, nullable=True)
    job_export_group = Column(String, nullable=True)
    job_export_project = Column(String, nullable=True)
    job_active = Column(Boolean, nullable=False, default=True)
# REMOVE job_disabled
    job_disabled = Column(Boolean, nullable=True, default=False)
    job_created_timestamp = Column(DateTime(timezone=True), nullable=False, default=DBHelpers.now)
    job_updated_timestamp = Column(DateTime(timezone=True), nullable=False, default=DBHelpers.now, onupdate=DBHelpers.now)
    run_frequency_seconds = Column(Integer, nullable=False)
    job_secrets = Column(String, nullable=True)
    job_details = Column(String, nullable=False)

    def __init__(self, job_type, job_user, job_project, job_export_group, job_export_project, run_frequency_seconds, job_secrets, job_details):
        self.export_id = DBHelpers.hashEncode("job__{0}__{1}".format(
            job_type,
            time()
        ))
        self.job_type = job_type
        self.job_user = job_user
        self.job_project = job_project
        self.job_export_group = job_export_group
        self.job_export_project = job_export_project
        self.run_frequency_seconds = run_frequency_seconds
        self.job_secrets = job_secrets
        self.job_details = job_details

    def __repr__(self):
        return "<Job {0} of type {1} ({2}/{3})>".format(
            self.job_id,
            self.job_type,
            self.job_user,
            self.job_project
        )


class Execution(db.Base):
    __tablename__ = "executions"
    execution_id = Column(Integer, primary_key=True)
    external_execution_id = Column(String, nullable=False, unique=True)
    execution_type = Column(String, nullable=False)
    execution_started_timestamp = Column(DateTime(timezone=True), nullable=True, default=None)
    execution_ended_timestamp = Column(DateTime(timezone=True), nullable=True, default=None)
    execution_status = Column(Integer, nullable=False, default=StatusTypes.code["Initializing"])
# REMOVE execution_error_code
    execution_error_code = Column(Integer, nullable=True, default=0)
    execution_details = Column(String, nullable=False)
    job_run_id = Column(Integer, nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.job_id"), nullable=False)
    jobs = relationship("Job", backref=backref("executions", lazy=True))

    def __init__(self, execution_type, job_id, job_run_id, execution_details):
        self.external_execution_id = DBHelpers.hashEncode("execution__{0}__{1}__{2}".format(
            execution_type,
            job_id,
            time()
        ))
        self.execution_type = execution_type
        self.execution_details = execution_details
        self.job_id = job_id
        self.job_run_id = job_run_id

    def __repr__(self):
        return "<Execution {0} of type {1} belonging to export_id {2}>".format(
            self.external_execution_id,
            self.jobs.job_type,
            self.jobs.export_id
        )

class JobRun(db.Base):
    __tablename__ = "job_runs"
    job_run_pk = Column(Integer, primary_key=True)
    job_id = Column(Integer, nullable=False)
    job_run_id = Column(Integer, nullable=False)
    job_run_started_timestamp = Column(DateTime(timezone=True), nullable=False, default=DBHelpers.now)
    job_run_updated_timestamp = Column(DateTime(timezone=True), nullable=False, default=DBHelpers.now)
    execution_type = Column(String, nullable=False)
    associated_execution_id = Column(Integer, nullable=False)
    last_successful_execution_id = Column(Integer, nullable=True)
#    last_successful_execution_id = Column(Integer, ForeignKey("executions.execution_id"), nullable=True)
#    executions = relationship("Execution", backref=backref("job_runs", lazy=True))

    def __init__(self, job_id, job_run_id, execution_type, associated_execution_id, last_successful_execution_id):
        self.job_id = job_id
        self.job_run_id = job_run_id
        self.execution_type = execution_type
        self.associated_execution_id = associated_execution_id
        self.last_successful_execution_id = last_successful_execution_id

    def __repr__(self):
        return "<JobRun {0} belonging to job_id {1} for execution_type {2}>".format(
            self.job_run_id,
            self.job_id,
            self.execution_type
        )

class Metric(db.Base):
    __tablename__ = "metrics"
    metric_key = Column(Integer, primary_key=True)
    collection_timestamp = Column(DateTime(timezone=True), nullable=False, default=DBHelpers.now)
    domino_api_healthy = Column(Boolean, nullable=False)
    domino_docker_registry_healthy = Column(Boolean, nullable=False)
    external_docker_registry_healthy = Column(Boolean, nullable=False)
    external_s3_bucket_healthy = Column(Boolean, nullable=False)

    def __init__(self, domino_api_healthy, domino_docker_registry_healthy, external_docker_registry_healthy, external_s3_bucket_healthy):
        self.domino_api_healthy = domino_api_healthy
        self.domino_docker_registry_healthy = domino_docker_registry_healthy
        self.external_docker_registry_healthy = external_docker_registry_healthy
        self.external_s3_bucket_healthy = external_s3_bucket_healthy

    def __repr__(self):
        return "<Metric collected at {0} with values (domino_api_healthy: {1}, domino_docker_registry_healthy: {2}, external_docker_registry_healthy: {3}, external_s3_bucket_healthy: {4})".format(
            self.collection_timestamp,
            self.domino_api_healthy,
            self.domino_docker_registry_healthy,
            self.external_docker_registry_healthy,
            self.external_s3_bucket_healthy
        )