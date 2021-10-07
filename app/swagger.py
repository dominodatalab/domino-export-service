from app import app

from flask import make_response
from flask import render_template
from flask import request
from flask_swagger_ui import get_swaggerui_blueprint

swaggerURL = "/docs"
apiConfig = "/swagger"
openapiTemplate = app.config.get("OPENAPI_YAML_TEMPLATE_FILE", "domino-export-spec.yaml")

@app.route(apiConfig, methods=["GET"])
def openapiConfig():
    response = make_response(render_template(openapiTemplate, exportServiceHost = request.host_url))
    response.headers["Content-Type"] = "application/x-yaml; charset=utf-8"
    return response

swaggerui_blueprint = get_swaggerui_blueprint(swaggerURL, apiConfig)

app.register_blueprint(swaggerui_blueprint, url_prefix=swaggerURL)