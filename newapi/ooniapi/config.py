from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os

from flask import request

import statsd  # debdeps: python3-statsd

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

CACHE_DEFAULT_TIMEOUT = None
CACHE_CONFIG = {"CACHE_TYPE": "simple"}

APP_ENV = os.environ.get("APP_ENV", "development")
# FIXME read from conf file
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres@localhost:5432/metadb"
)
DATABASE_STATEMENT_TIMEOUT = int(
    os.environ.get("DATABASE_STATEMENT_TIMEOUT", "0")
)  # to kill long-running statements ASAP

BASE_URL = os.environ.get("BASE_URL", "https://api.ooni.io/")

# FIXME remove?
AUTOCLAVED_BASE_URL = os.environ.get(
    "AUTOCLAVED_BASE_URL", "http://datacollector.infra.ooni.io/ooni-public/autoclaved/"
)

CENTRIFUGATION_BASE_URL = os.environ.get(
    "CENTRIFUGATION_BASE_URL",
    "http://datacollector.infra.ooni.io/ooni-public/centrifugation/",
)

# FIXME remove?
# S3 related configuration
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID", None)
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", None)
S3_SESSION_TOKEN = os.environ.get("S3_SESSION_TOKEN", None)
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", None)

# As of 2017-07-18 635830 is the latest index in the database
REPORT_INDEX_OFFSET = int(os.environ.get("REPORT_INDEX_OFFSET", "635830"))

REQID_HDR = "X-Request-ID"

metrics = statsd.StatsClient("localhost", 8125, prefix="ooni-api")

def request_id():
    if request:
        return request.headers.get(REQID_HDR)
    return None
