# -*- coding: utf-8 -*-
"""Domino API Library

This is a rewrite of the Domino Python API library (python-domino -
https://github.com/dominodatalab/python-domino) to support additional and
undocumented API calls and handling of post-processing tasks.
"""

import requests
import urllib3
import os
import io
import json
import smart_open
import re

class DominoAPIError(Exception):
    pass

class DominoAPIKeyInvalid(DominoAPIError):
    pass

class DominoAPIUnauthorized(DominoAPIError):
    pass

class DominoAPINotFound(DominoAPIError):
    pass

class DominoAPIBadRequest(DominoAPIError):
    pass

class DominoAPIComputeEnvironmentRevisionNotAvailable(DominoAPIError):
    pass

class DominoAPIUnexpectedError(DominoAPIError):
    def __init__(self, *args):
        if args:        
            self.message = "Domino API gave HTTP response status code {0} with message '{1}'".format(
                args[0],
                args[1]
            )
        else:
            self.message = None

    def __str__(self):
        if self.message:
            return "{0}".format(self.message)
        else:
            return ""


class DominoAPISession(object):
    """Creates a requests.Session connection to a Domino API server

    TODO

    """
    def __init__(self, dominoHost, dominoApiKey, verifySSL = True):
        self.__session = requests.Session()

        if verifySSL == False:
            self.__session.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        elif verifySSL:
            self.__session.verify = verifySSL

        self.__session.headers.update({
            "X-Domino-Api-Key": dominoApiKey
        })
        self.__dominoHost = dominoHost
        self.__dominoApiKey = dominoApiKey
        self.__dominoVersion = self.version()


# KEEP
    # GET /version
    def version(self):
        api = self.__dominoVersionAPI(self.__session, self.__dominoHost)
        return api.makeRequest()

# KEEP
    # GET /v1/auth/principal
    def authPrincipal(self):
        api = self.__dominoAuthPrincipal(self.__session, self.__dominoHost)
        return api.makeRequest()

# REMOVE?
    # GET /v4/users?userName={userName}
    def getUserDataByUserName(self, userName):
        api = self.__dominoGetUserDataByUserName(self.__session, self.__dominoHost)
        return api.makeRequest(userName)

# REMOVE?
    # GET /v4/projects?name={projectName}&ownerId={ownerId}
    def listProjectsByUserID(self, userID):
        api = self.__dominoListProjectsByUserID(self.__session, self.__dominoHost)
        return api.makeRequest(userID)

# KEEP
# NEED TO UPDATE
    # GET /v4/projects
    def listProjects(self):
        api = self.__dominoListProjects(self.__session, self.__dominoHost)
        return api.makeRequest()

# KEEP
    # GET /v4/gateway/projects/findProjectByOwnerAndName?ownerName={userName}&projectName={projectName}
    def findProjectByOwnerAndName(self, userName, projectName):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        api = self.__dominoFindProjectByOwnerAndName(self.__session, self.__dominoHost)
        response = api.makeRequest(userName, projectName)

        if response.get("status_code", requests.codes.ok) == requests.codes.not_found:
            raise(DominoAPINotFound)
        elif response.get("status_code", requests.codes.ok) == requests.codes.forbidden:
            raise(DominoAPIUnauthorized)
        elif response.get("status_code", requests.codes.ok) != requests.codes.ok:
            raise(DominoAPIUnexpectedError(response.get("status_code", 0), response.get("message", '')))

        return response

# KEEP
    # GET /v4/projects/{projectID}/commits
    def projectCommitIDsByProjectID(self, projectID):
        api = self.__dominoProjectCommitIDs(self.__session, self.__dominoHost)
        response = api.makeRequest(projectID)

        if response.get("status_code", requests.codes.ok) == requests.codes.not_found:
            raise(DominoAPINotFound)
        elif response.get("status_code", requests.codes.ok) == requests.codes.forbidden:
            raise(DominoAPIUnauthorized)
        elif response.get("status_code", requests.codes.ok) != requests.codes.ok:
            raise(DominoAPIUnexpectedError(response.get("status_code", 0), response.get("message", '')))

        return response

    # GET /v4/projects/{projectID}/commits
    def projectCommitIDs(self, userName, projectName):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        projectInfo = self.findProjectByOwnerAndName(userName, projectName)
        response = self.projectCommitIDsByProjectID(projectInfo["id"])

        return response

# KEEP
    # GET /v4/projects/{projectID}/commits/head/files/{path}
    def projectListLatestFilesByProjectID(self, projectID):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        api = self.__dominoProjectListLatestFiles(self.__session, self.__dominoHost)
        response = api.makeRequest(projectID)

        if response.get("status_code", requests.codes.ok) == requests.codes.not_found:
            raise(DominoAPINotFound)
        elif response.get("status_code", requests.codes.ok) == requests.codes.forbidden:
            raise(DominoAPIUnauthorized)
        elif response.get("status_code", requests.codes.ok) != requests.codes.ok:
            raise(DominoAPIUnexpectedError(response.get("status_code", 0), response.get("message", '')))

        return response

# KEEP
    # GET /v4/projects/{projectID}/commits/head/files/{path}
    def projectListLatestFiles(self, userName, projectName):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        projectInfo = self.findProjectByOwnerAndName(userName, projectName)
        response = self.projectListLatestFilesByProjectID(projectInfo["id"])

        return response

# KEEP
    # GET /v1/projects/{userName}/{projectName}/blobs/{blobID}
    def projectFileContentsByKeyID(self, userName, projectName, blobID):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        # Use this verify project access
        projectInfo = self.findProjectByOwnerAndName(userName, projectName)
    
        api = self.__dominoProjectFileContentsByKeyID(self.__session, self.__dominoHost)
        response = api.makeRequest(userName, projectName, blobID)

        if type(response) is dict:
            if response.get("status_code", requests.codes.ok) == requests.codes.not_found:
                raise(DominoAPINotFound)
            elif response.get("status_code", requests.codes.ok) == requests.codes.forbidden:
                raise(DominoAPIUnauthorized)
            elif response.get("status_code", requests.codes.ok) != requests.codes.ok:
                raise(DominoAPIUnexpectedError(response.get("status_code", 0), response.get("message", '')))

        return response

# DELETE?
    # GET /environments/{environmentID}/json
    def environmentInfo(self, environmentID):
        api = self.__dominoEnvironmentInfo(self.__session, self.__dominoHost)
        return api.makeRequest(environmentID)

# KEEP
    # GET /v1/environments
    def environmentsDetail(self):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        api = self.__dominoAllEnvironmentsDetails(self.__session, self.__dominoHost)
        response = api.makeRequest()

        if response.get("status_code", requests.codes.ok) == requests.codes.not_found:
            raise(DominoAPINotFound)
        elif response.get("status_code", requests.codes.ok) == requests.codes.forbidden:
            raise(DominoAPIUnauthorized)
        elif response.get("status_code", requests.codes.ok) != requests.codes.ok:
            raise(DominoAPIUnexpectedError(response.get("status_code", 0), response.get("message", '')))

        return response

# KEEP
    # GET /v1/environments
    def environmentDetailByID(self, environmentID):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        allEnvironments = self.environmentsDetail()["data"]
        environDetail = {
            "id": None,
            "name": None,
            "visibility": None
        }
        for environment in allEnvironments:
            if environment["id"] == environmentID:
                environDetail = environment
                break

        return environDetail


# KEEP
    # GET /environments/{environmentID}/json
    def environmentURLByRevision(self, environmentID, revisionNumber):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        api = self.__dominoEnvironmentInfo(self.__session, self.__dominoHost)
        response = api.makeRequest(environmentID)

        if response.get("status_code", requests.codes.ok) == requests.codes.not_found:
            raise(DominoAPINotFound)
        elif response.get("status_code", requests.codes.ok) == requests.codes.forbidden:
            raise(DominoAPIUnauthorized)
        elif response.get("status_code", requests.codes.ok) != requests.codes.ok:
            raise(DominoAPIUnexpectedError(response.get("status_code", 0), response.get("message", '')))

        environmentURL = None
        for revision in response.get("revisions", []):
            if revision["number"] == revisionNumber:
                environmentURL = revision.get("dockerImageName", None)
            
        if environmentURL == None:
            raise(DominoAPIComputeEnvironmentRevisionNotAvailable)
        
        return environmentURL

# KEEP
    def projectComputeEnvironment(self, projectID):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        api = self.__dominoProjectUseableEnvironments(self.__session, self.__dominoHost)
        response = api.makeRequest(projectID)

        if response.get("status_code", requests.codes.ok) == requests.codes.not_found:
            raise(DominoAPINotFound)
        elif response.get("status_code", requests.codes.ok) == requests.codes.forbidden:
            raise(DominoAPIUnauthorized)
        elif response.get("status_code", requests.codes.ok) != requests.codes.ok:
            raise(DominoAPIUnexpectedError(response.get("status_code", 0), response.get("message", '')))

        computeEnvironment = response.get("currentlySelectedEnvironment", None)
        if computeEnvironment == None:
            raise(DominoAPIComputeEnvironmentRevisionNotAvailable)

        return computeEnvironment

# KEEP
    def isValidAPIKey(self):
        dominoUserData = {
            "isAnonymous": True
        }
        try:
            dominoUserData = self.authPrincipal()
        except:
            pass

        return not dominoUserData["isAnonymous"]

    def hasAccessToComputeEnvironment(self, computeEnvID):
        environmentInfo = None
        try:
            environmentInfo = self.environmentInfo(computeEnvID)
        except:
            pass
        return environmentInfo != None

    def hasAccessToProject(self, userName, projectName):
        authorized = False
        try:
            authorized = "ChangeProjectSettings" in self.findProjectByOwnerAndName(userName, projectName).get("allowedOperations", [])
        except:
            pass
        return authorized

# KEEP
    def projectComputeEnvironmentAndRevision(self, userName, projectName):
        if not self.isValidAPIKey():
            raise(DominoAPIKeyInvalid)

        computeEnvironmentRevision = {
            "id": None,
            "revision": None
        }

        projectID = self.findProjectByOwnerAndName(userName, projectName)["id"]
        computeEnvironment = self.projectComputeEnvironment(projectID)
        computeEnvironmentRevision["id"] = computeEnvironment["id"]       
        computeEnvironmentRevision["revision"] = computeEnvironment["v2EnvironmentDetails"]["selectedRevision"]

        return computeEnvironmentRevision

    class __dominoRequestBase:
        def __init__(self, session, dominoHost, postProcessResults = True):
            self.uriBase = "{dominoHost}/health"
            self.uriParams = {
                "dominoHost": dominoHost
            }
            self.requestsHandler = session.get
            self.responseDataType = "text"
            self.postProcessResults = postProcessResults

        def makeRequest(self, data = None, json = None):
            uri = self.uriBase.format(**self.uriParams)

            (respCode, respData) = self._request(uri = uri, data = data, json = json)
            
            if self.postProcessResults:
                respData = self._postProcess(respCode, respData)
                
            return respData

        def _request(self, uri, data, json):
            response = self.requestsHandler(uri, data = data, json = json)
            respCode = response.status_code

            respData = None
            if self.responseDataType == "text":
                respData = response.text
            else:
                respData = response.content

            return (respCode, respData)

        def _postProcess(self, respCode, respData):
            return respData

    class __dominoVersionAPI(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/version"
            self.requestsHandler = session.get
        
        def _postProcess(self, respCode, respData):
            return json.loads(respData)
        
    class __dominoAuthPrincipal(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v4/auth/principal"
            self.requestsHandler = session.get
        
        def _postProcess(self, respCode, respData):
            return json.loads(respData)

        
    class __dominoGetUserDataByUserName(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v4/users?userName={userName}"
            self.requestsHandler = session.get

        def makeRequest(self, userName):
            self.uriParams["userName"] = userName
            return super().makeRequest()

        def _postProcess(self, respCode, respData):
            return json.loads(respData)[0]

        
    class __dominoListProjectsByUserID(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v4/projects?ownerId={userID}"
            self.requestsHandler = session.get

        def makeRequest(self, userID):
            self.uriParams["userID"] = userID
            return super().makeRequest()

        def _postProcess(self, respCode, respData):
            return json.loads(respData)

    class __dominoListProjects(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v4/projects"
            self.requestsHandler = session.get

        def _postProcess(self, respCode, respData):
            return json.loads(respData)

    class __dominoFindProjectByOwnerAndName(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v4/gateway/projects/findProjectByOwnerAndName?ownerName={userName}&projectName={projectName}"
            self.requestsHandler = session.get

        def makeRequest(self, userName, projectName):
            self.uriParams["userName"] = userName
            self.uriParams["projectName"] = projectName
            return super().makeRequest()

        def _postProcess(self, respCode, respData):
            # Default error response
            resp = {
                "message": "unexpected error",
                "status_code": respCode
            }

            if respCode == requests.codes.ok:
                resp = json.loads(respData)
            elif respCode == requests.codes.not_found:
                resp["message"] = "project not found"
            elif respCode == requests.codes.forbidden:
                resp["message"] = "not authorized to access project"

            return resp

    class __dominoProjectCommitIDs(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v4/projects/{projectID}/commits"
            self.requestsHandler = session.get

        def makeRequest(self, projectID):
            self.uriParams["projectID"] = projectID
            return super().makeRequest()

        def _postProcess(self, respCode, respData):
            # Default error response
            resp = {
                "message": "unexpected error",
                "status_code": respCode
            }

            if respCode == requests.codes.ok:
                resp = {"commits": json.loads(respData)}
            elif respCode == requests.codes.not_found:
                resp["message"] = "project not found"
            elif respCode == requests.codes.forbidden:
                resp["message"] = "not authorized to access project"
            elif respCode == requests.codes.internal_server_error:
                reNotFound = re.compile("NoSuchElementException: key not found")
                reForbidden = re.compile("Don't recognize principal AnonymousPrincipal")

                if reNotFound.search(respData):
                    resp["status_code"] = requests.codes.not_found
                    resp["message"] = "project not found"
                elif reForbidden.search(respData):
                    resp["status_code"] = requests.codes.forbidden
                    resp["message"] = "not authorized to access project"

            return resp


    class __dominoProjectListLatestFiles(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v4/projects/{projectID}/commits/head/files//"
            self.requestsHandler = session.get

        def makeRequest(self, projectID):
            self.uriParams["projectID"] = projectID
            return super().makeRequest()

        def _postProcess(self, respCode, respData):
            # Default error response
            resp = {
                "message": "unexpected error",
                "status_code": respCode
            }

            if respCode == requests.codes.ok:
                resp = {"files": json.loads(respData)}
            elif respCode == requests.codes.not_found:
                resp["message"] = "project not found"
            elif respCode == requests.codes.forbidden:
                resp["message"] = "not authorized to access project"
            elif respCode == requests.codes.internal_server_error:
                reNotFound1 = re.compile("Error cloning git repository .*?: Invalid remote: origin")
                reNotFound2 = re.compile("NoSuchElementException: key not found")

                if reNotFound1.search(respData) or reNotFound2.search(respData):
                    resp["status_code"] = requests.codes.not_found
                    resp["message"] = "project not found"

            return resp

    class __dominoProjectUseableEnvironments(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v4/projects/{projectID}/useableEnvironments"
            self.requestsHandler = session.get

        def makeRequest(self, projectID):
            self.uriParams["projectID"] = projectID
            return super().makeRequest()

        def _postProcess(self, respCode, respData):
            # Default error response
            resp = {
                "message": "unexpected error",
                "status_code": respCode
            }

            if respCode == requests.codes.ok:
                resp = json.loads(respData)
            elif respCode == requests.codes.not_found:
                resp["message"] = "project not found"
            elif respCode == requests.codes.forbidden:
                resp["message"] = "not authorized to access project"

            return resp

    class __dominoAllEnvironmentsDetails(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v1/environments"
            self.requestsHandler = session.get

        def makeRequest(self):
            return super().makeRequest()

        def _postProcess(self, respCode, respData):
            # Default error response
            resp = {
                "message": "unexpected error",
                "status_code": respCode
            }

            if respCode == requests.codes.ok:
                resp = json.loads(respData)
            elif respCode == requests.codes.forbidden:
                resp["message"] = "not authorized to access compute environment"

            return resp

    class __dominoEnvironmentInfo(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/environments/{environmentID}/json"
            self.requestsHandler = session.get

        def makeRequest(self, environmentID):
            self.uriParams["environmentID"] = environmentID
            return super().makeRequest()

        def _postProcess(self, respCode, respData):
            # Default error response
            resp = {
                "message": "unexpected error",
                "status_code": respCode
            }

            if respCode == requests.codes.ok:
                resp = json.loads(respData)
            elif respCode == requests.codes.internal_server_error:
                reNotFound = re.compile("Error Message: (Environment [0-9a-z]{24} does not exist)\.")
                reForbidden = re.compile("Error Message: (Not authorized: User .*? is not allowed to view environment [0-9a-z]{24}).")

                if reForbidden.search(respData):
                    resp["status_code"] = requests.codes.forbidden
                    resp["message"] = "not authorized to access compute environment"
                elif reNotFound.search(respData):
                    resp["status_code"] = requests.codes.not_found
                    resp["message"] = "compute environment not found"

            return resp

    class __dominoProjectFileContentsByKeyID(__dominoRequestBase):
        def __init__(self, session, dominoHost):
            super().__init__(session, dominoHost)
            self.uriBase = "{dominoHost}/v1/projects/{userName}/{projectName}/blobs/{blobID}"
            self.requestsHandler = session.get
            self.__requestObj = None
            self.iterator = None
            self.__streamChunkSize = io.DEFAULT_BUFFER_SIZE

        def makeRequest(self, userName, projectName, blobID):
            self.uriParams["userName"] = userName
            self.uriParams["projectName"] = projectName
            self.uriParams["blobID"] = blobID

            return super().makeRequest()

        def _request(self, uri, data, json):
            response = self.requestsHandler(uri, data = data, json = json, stream = True)
            respCode = response.status_code
            self.iterator = response.iter_content(chunk_size = self.__streamChunkSize)

            return (respCode, self.iterator)

        def _postProcess(self, respCode, respData):
            # Default error response
            resp = {
                "message": "unexpected error",
                "status_code": respCode
            }

            if respCode == requests.codes.ok:
                resp = respData
            elif respCode == requests.codes.forbidden:
                resp["message"] = "not authorized to access file"
            elif respCode == requests.codes.not_found:
                resp["message"] = "file not found"
            elif respCode == requests.codes.internal_server_error:
                reNotFound = re.compile("NoSuchElementException: key not found")
                if reNotFound.search(respData):
                    resp["status_code"] = requests.codes.not_found
                    resp["message"] = "file not found"

            return resp
