from app import app
from app.dbcommon import DBCommon
from app.dockerclient import DockerClient
from domino import DominoAPISession

import boto3
from datetime import datetime, timedelta
from urllib.parse import urlparse
import stopit


class Cleanup(object):
    def __init__(self, dbSession):
        self.dbSession = dbSession
        self.dbCommon = DBCommon(self.dbSession)

    def pruneMetrics(self):
        dt = datetime.today() - timedelta(days = app.config.get("DATABASE_HISTORY_AGE_DAYS", 30))
        metrics = self.dbCommon.getAllMetricsPriorToDatetime(dt)
        metrics.delete(synchronize_session='fetch')
        self.dbSession.commit();

    def pruneExecutions(self):
        dt = datetime.today() - timedelta(days = app.config.get("DATABASE_HISTORY_AGE_DAYS", 30))
        executions = self.dbCommon.getAllExecutionsPriorToDatetime(dt)
        executionIDs = [x[0] for x in executions.values("execution_id")]
        jobruns = self.dbCommon.getJobRunByExecutionIDs(executionIDs)

        jobruns.delete(synchronize_session='fetch')
        executions.delete(synchronize_session='fetch')
        self.dbSession.commit();

class HealthMetrics(object):
    def __init__(self):
        pass

    @stopit.threading_timeoutable(default=False)
    def isDominoAPIHealthy(self):
        healthy = True

        try:
            DominoAPISession(app.config["DOMINO_API_SERVER"], "", verifySSL = app.config["DOMINO_API_SERVER_VERIFY_SSL"])
        except:
            healthy = False

        return healthy

    @stopit.threading_timeoutable(default=False)
    def isDominoDockerRegistryHealthy(self):
        healthy = True
        dominoRegistry = app.config.get("DOMINO_DOCKER_REGISTRY", None)
        registry = {
            "url": dominoRegistry,
            "username": app.config.get("DOMINO_DOCKER_REGISTRY_USER", None),
            "password": app.config.get("DOMINO_DOCKER_REGISTRY_PASSWORD", None)
        }

        if dominoRegistry:
            try:
                dockerClient = DockerClient(registry, {})
                healthy = dockerClient.dominoRegistryHealth().get("online", False)
            except:
                healthy = False

        return healthy

    @stopit.threading_timeoutable(default=False)
    def isExternalDockerRegistryHealthy(self):
        healthy = True
        registry = {
            "url": app.config["EXPORTS_DOCKER_REGISTRY"],
            "username": app.config.get("EXPORTS_DOCKER_REGISTRY_USERNAME", None),
            "password": app.config.get("EXPORTS_DOCKER_REGISTRY_PASSWORD", None)
        }

        try:
            dockerClient = DockerClient({}, registry)
            healthy = dockerClient.externalRegistryHealth().get("online", False)
        except:
            healthy = False

        return healthy

    @stopit.threading_timeoutable(default=False)
    def isS3BucketHealthy(self):
        healthy = True
        s3Bucket = urlparse(app.config["EXPORTS_PROJECT_FILES_S3_BUCKET"])

        try:
            s3 = boto3.resource('s3')
            s3.meta.client.head_bucket(Bucket=s3Bucket.netloc)
        except:
            healthy = False
    
        return healthy

class AdministrationAPI(object):
    def __init__(self, dbSession):
        self.dbSession = dbSession
        self.dbCommon = DBCommon(self.dbSession)
        self.healthMetrics = HealthMetrics()

    def health(self):
        import pytz
        import datetime

        respCode = 200
        (respCode, version) = self.version()
        collectionTimestamp = datetime.datetime.utcnow()
        dominoAPIHealthy = None
        dominoDockerRegistryHealthy = None
        externalDockerRegistryHealthy = None
        S3BucketHealthy = None

        metrics = self.dbCommon.getLatestHealthMetrics()
        if metrics:
            collectionTimestamp = metrics.collection_timestamp
            dominoAPIHealthy = metrics.domino_api_healthy
            dominoDockerRegistryHealthy = metrics.domino_docker_registry_healthy
            externalDockerRegistryHealthy = metrics.external_docker_registry_healthy
            S3BucketHealthy = metrics.external_s3_bucket_healthy
        healthStatus = {
            "overall_healthy": dominoAPIHealthy and dominoDockerRegistryHealthy and externalDockerRegistryHealthy and S3BucketHealthy,
            "api_version": version["api_version"],
            "health_check_timestamp": str(pytz.utc.localize(collectionTimestamp)),
            "domino_platform_connection_healthy": dominoAPIHealthy,
            "domino_registry_connection_healthy": dominoDockerRegistryHealthy,
            "s3_connection_healthy": S3BucketHealthy,
            "external_registry_connection_healthy": externalDockerRegistryHealthy,
            "last_successful_backup_job_timestamp": None
        }

        return (respCode, healthStatus)

    def version(self):
        respCode = 200
        version = {
            "api_version": app.config["API_VERSION"]
        }
        return (respCode, version)