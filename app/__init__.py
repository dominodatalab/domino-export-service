from flask import Flask
import logging
from os import makedirs
from os.path import dirname

class ReverseProxied(object):
    def __init__(self, app):
        self.app = app
    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]

        return self.app(environ, start_response)

from app.database import Database
db = Database()

try:
    from app.encryption import Encrypter
    encrypter = Encrypter()
    from app.scheduling import Scheduler
    scheduler = Scheduler()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("app.default_config")
    app.config.from_pyfile("config.py", silent=True)

    makePaths = [
        app.config.get("SQLALCHEMY_DATABASE_FILE", None),
        app.config.get("ENCRYPTION_KEY_FILE", None),
        app.config.get("FLASK_LOGGING_FILE", None)
    ]
    [makedirs(name = dirname(d), exist_ok = True) for d in makePaths if d]

    if not app.config.get("DEBUG", False):
        logLevel = logging.INFO
    else:
        logLevel = logging.DEBUG
    logging.basicConfig(filename=app.config["FLASK_LOGGING_FILE"], level=logLevel)

    app.wsgi_app = ReverseProxied(app.wsgi_app)

    from app import api
    from app import swagger

    encrypter.setKeyFile(app.config["ENCRYPTION_KEY_FILE"])

    db.start(app.config["SQLALCHEMY_DATABASE_URI"])
    db.initDB()
    db.updateServiceJobs()
    db.updateProjectJobs()
    db.updateExecutions()

    scheduler.start(maxWorkers = app.config["JOBS_MAX_CONCURRENT_WORKERS"])

except KeyboardInterrupt:
    print("Captured Ctrl+C Interrupt")
    db.close()
except Exception as e:
    raise(e)
finally:
    db.close()