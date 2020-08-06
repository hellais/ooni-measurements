from __future__ import absolute_import

import logging
import datetime
import os
import sys

from flask import Flask, json

# from flask_misaka import Misaka
# from flask_cors import CORS
from ooniapi.rate_limit_quotas import FlaskLimiter

from flasgger import Swagger

from flask_mail import Mail  # debdeps: python3-flask-mail

from flask_security import Security  # debdeps: python3-flask-security

from decimal import Decimal
from ooniapi.database import init_db

APP_DIR = os.path.dirname(__file__)


class FlaskJSONEncoder(json.JSONEncoder):
    # Special JSON encoder that handles dates
    def default(self, o):
        if isinstance(o, datetime.datetime):
            if o.tzinfo:
                # eg: '2015-09-25T23:14:42.588601+00:00'
                return o.isoformat("T")
            else:
                # No timezone present - assume UTC.
                # eg: '2015-09-25T23:14:42.588601Z'
                return o.isoformat("T") + "Z"

        if isinstance(o, datetime.date):
            return o.isoformat()

        if isinstance(o, Decimal):
            return float(o)

        if isinstance(o, set):
            return list(o)

        return json.JSONEncoder.default(self, o)


def validate_conf(app, conffile):
    """Fail early if the app configuration looks incorrect
    """
    conf_keys = (
        "AUTOCLAVED_BASE_URL",
        "BASE_URL",
        "CENTRIFUGATION_BASE_URL",
        "COLLECTORS",
        "DATABASE_STATEMENT_TIMEOUT",
        "DATABASE_URI_RO",
        "MAIL_PASSWORD",
        "MAIL_PORT",
        "MAIL_SERVER",
        "MAIL_USERNAME",
        "MAIL_USE_SSL",
        "S3_ACCESS_KEY_ID",
        "S3_ENDPOINT_URL",
        "S3_SECRET_ACCESS_KEY",
        "S3_SESSION_TOKEN",
    )
    for k in conf_keys:
        if k not in app.config:
            log = app.logger
            log.error(f"Missing configuration key {k} in {conffile}")
            # exit with 4 to terminate gunicorn
            sys.exit(4)


def init_app(app, testmode=False):
    # Load configurations defaults from ooniapi/config.py
    # and then from the file pointed by CONF
    # (defaults to /etc/ooni/api.conf)
    log = app.logger
    app.config.from_object("ooniapi.config")
    conffile = os.getenv("CONF", "/etc/ooni/api.conf")
    log.info(f"Loading conf from {conffile}")
    app.config.from_pyfile(conffile)
    validate_conf(app, conffile)
    log.info("Configuration loaded")

    # Prevent messy duplicate logs during testing
    #if not testmode:
    #    app.logger.addHandler(logging.StreamHandler())

    stage = app.config["APP_ENV"]
    if stage == "production":
        app.logger.setLevel(logging.INFO)
    elif stage == "development":
        app.logger.setLevel(logging.DEBUG)
        # Set the jinja templates to reload when in development
        app.jinja_env.auto_reload = True
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.config["DEBUG"] = True
    elif stage not in ("testing", "staging",):  # known envs according to Readme.md
        raise RuntimeError("Unexpected APP_ENV", stage)

    # md = Misaka(fenced_code=True)
    # md.init_app(app)

    # CORS(app, resources={r"/api/*": {"origins": "*"}})


def check_config(config):
    pass


def create_app(*args, testmode=False, **kw):
    from ooniapi import views

    app = Flask(__name__)
    app.json_encoder = FlaskJSONEncoder
    log = app.logger

    # Order matters
    init_app(app, testmode=testmode)
    check_config(app.config)

    # Setup Database connector
    init_db(app)

    # Setup rate limiting
    # NOTE: the limits apply per-process. The number of processes is set in:
    # https://github.com/ooni/sysadmin/blob/master/ansible/roles/ooni-measurements/tasks/main.yml
    limits = dict(
        ipaddr_per_month=6000,
        token_per_month=6000,
        ipaddr_per_week=2000,
        token_per_week=2000,
        ipaddr_per_day=400,
        token_per_day=500,
    )
    # Whitelist Prometheus and AMS Explorer
    # TODO: move addrs to an external config file /etc/ooniapi.conf ?
    whitelist = ["37.218.245.43", "37.218.242.149"]
    app.limiter = FlaskLimiter(limits=limits, app=app, whitelisted_ipaddrs=whitelist)

    Swagger(app, parse=True)

    mail = Mail(app)

    security = Security(app, app.db_session)

    # FIXME
    views.register(app)

    # why is it `teardown_appcontext` and not `teardown_request` ?...
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        app.db_session.remove()

    @app.route("/health")
    def health():
        return "UP"
        # option httpchk GET /check
        # http-check expect string success

    log.debug("Routes:")
    for r in app.url_map.iter_rules():
        log.debug(f" {r.match} ")
    log.debug("----")

    return app
