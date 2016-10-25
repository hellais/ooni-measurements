from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from measurements.app import create_app
app = create_app()

@app.teardown_appcontext
def shutdown_session(exception=None):
    app.db_session.remove()
