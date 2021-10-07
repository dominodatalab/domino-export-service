from app import app
from app import db
import app.models as models
from app.projects import ProjectsAPI
from app.admin import AdministrationAPI

from flask import jsonify
from flask import make_response
from flask import request

app.config["API_VERSION"] = "v1"


@app.teardown_appcontext
def shutdown_session(exception=None):
    db.dbSession.remove()


@app.route("/health", methods=["GET"])
def health():
    adminAPI = AdministrationAPI(db.dbSession)
    (respCode, jsonData) = adminAPI.health()
    response = make_response(jsonify(jsonData), respCode)
    return response


@app.route("/version", methods=["GET"])
def version():
    adminAPI = AdministationAPI(db.dbSession)
    (respCode, jsonData) = adminAPI.version()
    response = make_response(jsonify(jsonData), respCode)
    return response


@app.route("/v1/projects/create", methods=["POST"])
def projectsCreate():
    dominoAPIKey = request.headers.get("X-Domino-Api-Key")
    projectsAPI = ProjectsAPI(dominoAPIKey, db.dbSession)

    requestData = request.get_json(force=True)
# Check for allowed characters
    username = requestData["username"]
# Check for allowed characters
    projectName= requestData["project_name"]
# Check for allowed characters
    exportGroupName = requestData["export_group_name"]
# Check for allowed characters
    exportProjectName = requestData["export_project_name"]

    (respCode, jsonData) = projectsAPI.create(username, projectName, exportGroupName, exportProjectName)

    if "application/json" not in request.headers.get("Content-Type", ""):
        jsonMessageFormat = "{MESSAGE}"
        if jsonData.get("message", None):
            jsonMessageFormat = "{ORIGINAL};  {MESSAGE}"

        jsonData["message"] = jsonMessageFormat.format(
            ORIGINAL = jsonData.get("message", None),
            MESSAGE = "Warning: request has been processed, but the 'Content-Type: application/json' header is missing"
        )

    response = make_response(jsonify(jsonData), respCode)
    return response


@app.route("/v1/projects/status", defaults={"identity": None, "projectName": None}, methods=["GET"])
@app.route("/v1/projects/status/<identity>", defaults={"projectName": None}, methods=["GET"])
@app.route("/v1/projects/status/<identity>/<projectName>", methods=["GET"])
def projectsStatus(identity, projectName):
    dominoAPIKey = request.headers.get("X-Domino-Api-Key")
    projectsAPI = ProjectsAPI(dominoAPIKey, db.dbSession)

    (respCode, jsonData) = projectsAPI.status(identity, projectName)
    response = make_response(jsonify(jsonData), respCode)
    return response


@app.route("/v1/projects/update/<identity>", methods=["PUT"])
def projectsUpdate(identity):
    dominoAPIKey = request.headers.get("X-Domino-Api-Key")
    projectsAPI = ProjectsAPI(dominoAPIKey, db.dbSession)

    requestData = request.get_json(force=True)
    updateAPIKey = requestData.get("update_api_key", False)
# Check for allowed characters
    exportGroupName = requestData.get("export_group_name", None)
# Check for allowed characters
    exportProjectName = requestData.get("export_project_name", None)
    disabled = requestData.get("disabled", None)

    (respCode, jsonData) = projectsAPI.update(identity, updateAPIKey, exportGroupName, exportProjectName, disabled)

    if not jsonData.get("message", None) and "application/json" not in request.headers.get("Content-Type", ""):
        jobData["message"] = "Warning: request has been processed, but the 'Content-Type: application/json' header is missing"

    response = make_response(jsonify(jsonData), respCode)
    return response
