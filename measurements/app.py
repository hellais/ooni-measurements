from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging
import datetime
import os

from flask import Flask, json
from flask_misaka import Misaka
from flask_cors import CORS

from measurements import config
from measurements.database import init_db

APP_DIR = os.path.dirname(__file__)

class FlaskJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime):
            if o.tzinfo:
                # eg: '2015-09-25T23:14:42.588601+00:00'
                return o.isoformat('T')
            else:
                # No timezone present - assume UTC.
                # eg: '2015-09-25T23:14:42.588601Z'
                return o.isoformat('T') + 'Z'

        if isinstance(o, datetime.date):
            return o.isoformat()

        if isinstance(o, Decimal):
            return float(o)

        return json.JSONEncoder.default(self, o)

def init_app(app):
    # We load configurations first from the config file (where some options
    # are overridable via environment variables) or from the config file
    # pointed to by the MEASUREMENTS_CONFIG environment variable.
    # The later overrides the former.
    app.config.from_object('measurements.config')
    app.config.from_envvar('MEASUREMENTS_CONFIG', silent=True)

    app.logger.addHandler(logging.StreamHandler())

    if app.config['APP_ENV'] == 'production':
        app.logger.setLevel(logging.WARNING)
    elif app.config['APP_ENV'] == 'development':
        app.logger.setLevel(logging.DEBUG)
        # Set the jinja templates to reload when in development
        app.jinja_env.auto_reload = True
        app.config['TEMPLATES_AUTO_RELOAD'] = True
        app.config['DEBUG'] = True
    else:
        raise RuntimeError('Unexpected APP_ENV, should be `production` or `development`', app.config['APP_ENV'])

    for key in app.config.keys():
        SECRET_SUBSTRINGS = ["_SECRET_", "DATABASE_URL"]
        # Do not log, even in debug, anything containing the word "SECRET" or "DATABASE_URL"
        if any([s in key for s in SECRET_SUBSTRINGS]):
            continue
        app.logger.debug("{}: {}".format(key, app.config[key]))

    md = Misaka(fenced_code=True)
    md.init_app(app)

    CORS(app, resources={r"/api/*": {"origins": "*"}})

def check_config(config):
    pass

def create_app(*args, **kw):
    from measurements import views

    app = Flask(__name__)
    app.json_encoder = FlaskJSONEncoder

    # Order matters
    init_app(app)
    check_config(app.config)

    init_db(app)

    views.register(app)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        app.db_session.remove()

    return app
