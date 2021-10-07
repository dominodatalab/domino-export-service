import docker
import re
from io import BytesIO
import json

class DockerException(Exception):
    pass

class DockerAPIError(DockerException):
    pass

class DockerNotFound(DockerException):
    pass

class DockerImageNotFound(DockerException):
    pass

class DockerInvalidRepository(DockerException):
    pass

class DockerBuildError(DockerException):
    pass

class DockerClient(object):
    def __init__(self, dominoDockerRegistry, externalDockerRegistry):
        self.__dockerClient = docker.from_env()
        self.__dockerClientAPI = docker.APIClient(base_url='unix://var/run/docker.sock')
        self.__dominoDockerRegistry = dominoDockerRegistry
        self.__externalDockerRegistry = externalDockerRegistry
        self.__raiseOnException = False

    def raiseOnException(self, roe = True):
        self.__raiseOnException = roe

    def __raiseErrorChain(self, e):
        if self.__raiseOnException:
            if type(e) == docker.errors.APIError:
                raise DockerAPIError() from e
            elif type(e) == docker.errors.NotFound:
                raise DockerNotFound() from e
            elif type(e) == docker.errors.ImageNotFound:
                raise DockerImageNotFound() from e
            elif type(e) == docker.errors.InvalidRepository:
                raise DockerInvalidRepository() from e
            elif type(e) == docker.errors.BuildError:
                raise DockerBuildError() from e
            else:
                raise DockerException() from e

    def clientHealth(self):
        status = {
            "online": False,
            "message": None
        }

        try:
            status["online"] = self.__dockerClient.ping()
        except Exception as e:
            self.__raiseErrorChain(e)
  
        return status

    def registryHealth(self, registry):
        status = {
            "online": False,
            "message": None
        }

        if self.clientHealth()["online"]:
            try:
                self.__dockerClient.login(
                    registry = registry["url"],
                    username = registry.get("username", None),
                    password = registry.get("password", None),
                    reauth = False
                )
                status["online"] = True
            except Exception as e:
                self.__raiseErrorChain(e)
                status["message"] = str(e)
        else:
            status["message"] = "Domino client unavailable"

        return status

    def dominoRegistryHealth(self):
        return self.registryHealth(self.__dominoDockerRegistry)

    def externalRegistryHealth(self):
        return self.registryHealth(self.__externalDockerRegistry)

    def cleanup(self):
        status = {
            "success": False,
            "message": None,
            "status": None
        }

        if self.clientHealth()["online"]:
            try:
                status["status"] = self.__dockerClientAPI.prune_builds()
                status["success"] = True
            except Exception as e:
                self.__raiseErrorChain(e)
                status["message"] = str(e)
        else:
            status["message"] = "Docker client unavailable"

    def build(self, dockerFileTemplatePath, dominoImageURL, exportImageURL):
        status = {
            "success": False,
            "message": None,
            "logs": None
        }

        if self.clientHealth()["online"] and self.dominoRegistryHealth()["online"]:
            try:
                # Grab the contents for a Dockerfile based on the Dockerfile template
                dockerFileText = None
                with open(dockerFileTemplatePath, "r") as dockerFileTemplate:
                    dockerFileText = dockerFileTemplate.read().format(
                        DOMINO_DOCKER_IMAGE = dominoImageURL
                    )

                dockerFile = BytesIO(dockerFileText.encode('utf-8'))

                # Perform the Docker build
                response = self.__processBuildLogs(self.__dockerClientAPI.build(fileobj = dockerFile, rm = False, tag = exportImageURL, decode = True))

                status["logs"] = response["stream"]
                if not response["error"]:
                    status["success"] = True
                else:
                    status["success"] = False
                    status["message"] = response["error"]
            except Exception as e:
                self.__raiseErrorChain(e)
                status["message"] = str(e)
        else:
            status["message"] = "Docker client or Domino registry unavailable"

        return status

    def __processBuildLogs(self, build):
        response = {
            "stream": [],
            "errorDetail": None,
            "error": None
        }

        for line in build:
            if "stream" in line:
                response["stream"].append(line["stream"])
            else:
                for k in line:
                    response[k] = line[k]

        return response

    def pull(self, imageURL):
        status = {
            "success": False,
            "message": None,
            "logs": None
        }

        if self.clientHealth()["online"] and self.dominoRegistryHealth()["online"]:
            try:
                if self.__dominoDockerRegistry.get("username", False) and self.__dominoDockerRegistry.get("password", False):
                    response = self.__processPullAndPushLogs(self.__dockerClientAPI.pull(repository = imageURL, stream = True, decode = True, auth_config = self.__dominoDockerRegistry))
                else:
                    response = self.__processPullAndPushLogs(self.__dockerClientAPI.pull(repository = imageURL, stream = True, decode = True))

                status["logs"] = response["stream"]
                if not response["error"]:
                    status["success"] = True
                else:
                    status["success"] = False
                    status["message"] = response["error"]
            except Exception as e:
                self.__raiseErrorChain(e)
                status["message"] = str(e)
        else:
            status["message"] = "Docker client or Domino registry unavailable"

        return status

    def push(self, imageURL):
        status = {
            "success": False,
            "message": None,
            "logs": None
        }

        if self.clientHealth()["online"] and self.externalRegistryHealth()["online"]:
            try:
                if self.__externalDockerRegistry.get("username", False) and self.__externalDockerRegistry.get("password", False):
                    response = self.__processPullAndPushLogs(self.__dockerClientAPI.push(repository = imageURL, stream = True, decode = True, auth_config = self.__externalDockerRegistry))
                else:
                    response = self.__processPullAndPushLogs(self.__dockerClientAPI.push(repository = imageURL, stream = True, decode = True))

                status["logs"] = response["stream"]
                if not response["error"]:
                    status["success"] = True
                else:
                    status["success"] = False
                    status["message"] = response["error"]
            except Exception as e:
                self.__raiseErrorChain(e)
                status["message"] = str(e)
        else:
            status["message"] = "Docker client or external registry unavailable"

        return status

    def __processPullAndPushLogs(self, build):
        response = {
            "stream": [],
            "errorDetail": None,
            "error": None
        }

        for line in build:
            if "status" in line:
                response["stream"].append(
                    "[{0}] {1} (progress: {2}/{3})".format(
                        line.get("id", "No ID"),
                        line.get("status", "No Status"),
                        line.get("progressDetail", {}).get("current", 0),
                        line.get("progressDetail", {}).get("total", 0)
                    )
                )
            else:
                for k in line:
                    response[k] = line[k]

        return response