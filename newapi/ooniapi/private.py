"""
prefix: /api/_

In here live private API endpoints for use only by OONI services. You should
not rely on these as they are likely to change, break in unexpected ways. Also
there is no versioning on them.
"""
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from urllib.parse import urljoin, urlencode

import math


from flask import Blueprint, current_app, request, abort
from flask.json import jsonify

from sqlalchemy import func, and_, or_, sql, select

from werkzeug.exceptions import BadRequest

from ooniapi.models import TEST_GROUPS, get_test_group_case
from ooniapi.countries import lookup_country

# The private API is exposed under the prefix /api/_
# e.g. https://api.ooni.io/api/_/test_names

api_private_blueprint = Blueprint("api_private", "measurements")

# TODO: configure tags for HTTP caching across where useful


def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days)):
        yield start_date + timedelta(n)


def cachedjson(interval_hours: int, *a, **kw):
    """Jsonify and add cache expiration"""
    resp = jsonify(*a, **kw)
    resp.cache_control.max_age = interval_hours * 3600
    return resp


@api_private_blueprint.route("/asn_by_month")
def api_private_asn_by_month():
    """Network count by month
    ---
    responses:
      '200':
        description: [{"date":"2018-08-31","value":4411}, ... ]
    """
    cols = [sql.text("networks_by_month"), sql.text("month")]
    q = select(cols).select_from(sql.table("global_by_month"))
    q = current_app.db_session.execute(q)
    li = [dict(date=r[1], value=r[0]) for r in q]
    return cachedjson(24, li)


@api_private_blueprint.route("/countries_by_month")
def api_private_countries_by_month():
    """Countries count by month
    ---
    responses:
      '200':
        description: TODO
    """
    cols = [sql.text("countries_by_month"), sql.text("month")]
    q = select(cols).select_from(sql.table("global_by_month"))
    q = current_app.db_session.execute(q)
    li = [dict(date=r[1], value=r[0]) for r in q]
    return cachedjson(24, li)


@api_private_blueprint.route("/runs_by_month")
def api_private_runs_by_month():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    # The query takes ~6s on local SSD @ AMS on 2018-04-04.
    # It was taking ~20s when it was fetching all the table from DB and doing grouping locally.
    # TODO: use-count-table
    # FIXME: support fastpath
    now = datetime.now()
    end_date = datetime(now.year, now.month, 1)
    start_date = end_date - relativedelta(months=24)
    rawsql = """SELECT
        date_trunc('month', report.test_start_time) AS test_start_month,
        count(*) AS count_1
        FROM report
        WHERE report.test_start_time >= :start_date
        AND report.test_start_time < :end_date
        GROUP BY test_start_month
    """
    params = dict(start_date=start_date, end_date=end_date)
    q = current_app.db_session.execute(rawsql, params)
    delta = relativedelta(months=+1, days=-1)
    result = [
        {"date": (bkt + delta).strftime("%Y-%m-%d"), "value": value}
        for bkt, value in sorted(q.fetchall())
    ]
    return jsonify(result)


@api_private_blueprint.route("/reports_per_day")
def api_private_reports_per_day():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    # TODO: use-count-table
    # FIXME: support fastpath
    rawsql = """SELECT
        count(date_trunc('day', report.test_start_time)) AS count_1,
        date_trunc('day', report.test_start_time) AS date_trunc_2
        FROM report
        GROUP BY date_trunc('day', report.test_start_time)
        ORDER BY date_trunc('day', report.test_start_time)
    """
    q = current_app.db_session.execute(rawsql)
    result = [{"count": count, "date": date.strftime("%Y-%m-%d")} for count, date in q]
    return jsonify(result)


@api_private_blueprint.route("/test_names", methods=["GET"])
def api_private_test_names():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    TEST_NAMES = {
        "bridge_reachability": "Bridge Reachability",
        "dash": "DASH",
        "dns_consistency": "DNS Consistency",
        "facebook_messenger": "Facebook Messenger",
        "http_header_field_manipulation": "HTTP Header Field Manipulation",
        "http_host": "HTTP Host",
        "http_invalid_request_line": "HTTP Invalid Request Line",
        "http_requests": "HTTP Requests",
        "meek_fronted_requests_test": "Meek Fronted Requests",
        "multi_protocol_traceroute": "Multi Protocol Traceroute",
        "ndt": "NDT",
        "psiphon": "Psiphon",
        "tcp_connect": "TCP Connect",
        "telegram": "Telegram",
        "tor": "Tor",
        "vanilla_tor": "Vanilla Tor",
        "web_connectivity": "Web Connectivity",
        "whatsapp": "WhatsApp",
    }
    test_names = [{"id": k, "name": v} for k, v in TEST_NAMES.items()]
    return cachedjson(48, test_names=test_names)


@api_private_blueprint.route("/countries", methods=["GET"])
def api_private_countries():
    """Summary of countries
    ---
    responses:
      '200':
        description: TODO
    """
    cols = [sql.text("measurement_count"), sql.text("probe_cc")]
    q = select(cols).select_from(sql.table("country_stats"))
    c = []
    for r in current_app.db_session.execute(q):
        try:
            name = lookup_country(r.probe_cc)
            c.append(dict(alpha_2=r.probe_cc, name=name, count=r.measurement_count))
        except KeyError:
            pass

    return jsonify(countries=c)


@api_private_blueprint.route("/quotas_summary", methods=["GET"])
def api_private_quotas_summary():
    """Summary on rate-limiting quotas.
    [(first ipaddr octet, remaining daily quota), ... ]
    """
    return jsonify(current_app.limiter.get_lowest_daily_quotas_summary())


@api_private_blueprint.route("/check_report_id", methods=["GET"])
def check_report_id():
    """Check if a report_id exists either in the fastpath table or in the
    report table. Used by https://github.com/ooni/probe/issues/1034
    ---
    responses:
      '200':
        description: TODO
    """
    report_id = request.args.get("report_id")
    rawsql = """SELECT COALESCE (
        (SELECT 1 FROM fastpath WHERE report_id = :rid LIMIT 1),
        (SELECT 1 FROM report WHERE report_id = :rid LIMIT 1)
    )"""
    try:
        q = current_app.db_session.execute(rawsql, dict(rid=report_id))
        found = q.fetchone()[0] is not None
        response = jsonify(dict(v=0, found=found))
        response.cache_control.max_age = 5
        return response
    except Exception as e:
        return jsonify(dict(v=0, error=str(e)))


def last_30days():
    first_day = datetime.now() - timedelta(31)
    first_day = datetime(first_day.year, first_day.month, first_day.day)

    last_day = datetime.now() - timedelta(1)
    last_day = datetime(last_day.year, last_day.month, last_day.day)

    for d in daterange(first_day, last_day):
        yield d.strftime("%Y-%m-%d")


def get_recent_network_coverage(probe_cc, test_groups):
    # FIXME
    return []
    where_clause = [
        sql.text("test_day >= current_date - interval '31 day'"),
        sql.text("test_day < current_date"),
        sql.text("probe_cc = :probe_cc"),
    ]
    if test_groups is not None:
        tg_or = []
        for tg in test_groups:
            try:
                tg_names = TEST_GROUPS[tg]
                tg_or += [
                    sql.literal_column("test_name") == tg_name for tg_name in tg_names
                ]
            except KeyError:
                raise BadRequest("invalid test_group")
        where_clause.append(or_(*tg_or))

    s = (
        select([sql.text("COUNT(DISTINCT probe_asn)"), sql.text("test_day")])
        .where(and_(*where_clause))
        .group_by(sql.text("test_day"))
        .order_by(sql.text("test_day"))
        .select_from(sql.table("ooexpl_daily_msm_count"))
    )

    network_map = {k: 0 for k in TEST_GROUPS.keys()}
    q = current_app.db_session.execute(s, {"probe_cc": probe_cc})
    for count, date in q:
        network_map[date.strftime("%Y-%m-%d")] = count

    network_coverage = []
    for test_day in last_30days():
        network_coverage.append(
            {"count": network_map.get(test_day, 0), "test_day": test_day}
        )
    return network_coverage


def get_recent_test_coverage(probe_cc):
    # FIXME
    return []

    s = (
        select(
            [
                sql.text("SUM(count)"),
                sql.text("test_day"),
                sql.text(get_test_group_case() + " AS test_group"),
            ]
        )
        .where(
            and_(
                sql.text("test_day >= (current_date - interval '31 day')"),
                # We exclude the last day to wait for the pipeline
                sql.text("test_day < current_date"),
                sql.text("probe_cc = :probe_cc"),
            )
        )
        .group_by(sql.text("test_group, test_day"))
        .order_by(sql.text("test_group, test_day"))
        .select_from(sql.table("ooexpl_daily_msm_count"))
    )

    coverage_map = {k: {} for k in TEST_GROUPS.keys()}
    q = current_app.db_session.execute(s, {"probe_cc": probe_cc})
    for count, test_day, test_group in q:
        coverage_map[test_group][test_day.strftime("%Y-%m-%d")] = int(count)

    test_coverage = []
    for test_group, coverage in coverage_map.items():
        for test_day in last_30days():
            test_coverage.append(
                {
                    "count": coverage_map[test_group].get(test_day, 0),
                    "test_day": test_day,
                    "test_group": test_group,
                }
            )

    return test_coverage


@api_private_blueprint.route("/test_coverage", methods=["GET"])
def api_private_test_coverage():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing probe_cc")

    test_groups = request.args.get("test_groups")
    if test_groups is not None:
        test_groups = test_groups.split(",")

    return jsonify(
        {
            "test_coverage": get_recent_test_coverage(probe_cc),
            "network_coverage": get_recent_network_coverage(probe_cc, test_groups),
        }
    )


@api_private_blueprint.route("/website_networks", methods=["GET"])
def api_private_website_network_tests():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing probe_cc")

    s = (
        select([sql.text("COUNT(*)"), sql.text("probe_asn")])
        .where(
            and_(
                sql.text("test_start_time >= current_date - interval '31 day'"),
                sql.text("test_start_time < current_date"),
                sql.text("probe_cc = :probe_cc"),
            )
        )
        .group_by(sql.text("probe_asn"))
        .order_by(sql.text("count DESC"))
        .select_from(
            sql.table("measurement").join(
                sql.table("report"),
                sql.text("report.report_no = measurement.report_no"),
            )
        )
    )

    results = []
    q = current_app.db_session.execute(s, {"probe_cc": probe_cc})
    for count, probe_asn in q:
        results.append({"count": int(count), "probe_asn": int(probe_asn)})
    return jsonify({"results": results})


sql_anomaly_count = sql.text(
    "COALESCE(sum(CASE WHEN anomaly = TRUE AND confirmed = FALSE AND msm_failure = FALSE THEN 1 ELSE 0 END), 0) AS anomaly_count"
)
sql_confirmed_count = sql.text(
    "COALESCE(sum(CASE WHEN confirmed = TRUE THEN 1 ELSE 0 END), 0) AS confirmed_count"
)
sql_failure_count = sql.text(
    "COALESCE(sum(CASE WHEN msm_failure = TRUE THEN 1 ELSE 0 END), 0) AS failure_count"
)


@api_private_blueprint.route("/website_stats", methods=["GET"])
def api_private_website_stats():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    url = request.args.get("input")

    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing probe_cc")

    probe_asn = request.args.get("probe_asn")
    if probe_asn is None:
        raise BadRequest("missing probe_asn")

    s = sql.text(
        """SELECT
d.test_day,
COALESCE(anomaly_count, 0) as anomaly_count,
COALESCE(confirmed_count, 0) as confirmed_count,
COALESCE(failure_count, 0) as failure_count,
COALESCE(total_count, 0) as total_count
FROM (
(
    SELECT
    date_trunc('day', (current_date - offs)) AS test_day
    FROM generate_series(0, 31, 1) AS offs
) d
LEFT OUTER JOIN
(
    SELECT
    test_day,
    SUM(anomaly_count) as anomaly_count,
    SUM(confirmed_count) as confirmed_count,
    SUM(failure_count) as failure_count,
    SUM(total_count) as total_count
    FROM ooexpl_wc_input_counts
    WHERE test_day >= current_date - interval '31 day'
    AND probe_cc =  :probe_cc
    AND probe_asn = :probe_asn
    AND input = :input
    GROUP BY test_day
) m
ON d.test_day = m.test_day
)
ORDER BY test_day;"""
    )

    results = []
    q = current_app.db_session.execute(
        s, {"probe_cc": probe_cc, "probe_asn": probe_asn, "input": url}
    )
    for test_day, anomaly_count, confirmed_count, failure_count, total_count in q:
        results.append(
            {
                "test_day": test_day,
                "anomaly_count": int(anomaly_count),
                "confirmed_count": int(confirmed_count),
                "failure_count": int(failure_count),
                "total_count": int(total_count),
            }
        )
    return jsonify({"results": results})


@api_private_blueprint.route("/website_urls", methods=["GET"])
def api_private_website_test_urls():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    limit = int(request.args.get("limit", 10))
    if limit <= 0:
        limit = 10
    offset = int(request.args.get("offset", 0))

    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing probe_cc")

    probe_asn = request.args.get("probe_asn")
    if probe_asn is None:
        raise BadRequest("missing probe_asn")

    probe_asn = int(probe_asn.replace("AS", ""))
    where_clause = [
        sql.text("test_day >= current_date - interval '31 day'"),
        sql.text("probe_cc = :probe_cc"),
        sql.text("probe_asn = :probe_asn"),
    ]
    query_params = {"probe_cc": probe_cc, "probe_asn": probe_asn}

    row = current_app.db_session.execute(
        select([sql.text("COUNT(DISTINCT input)")])
        .where(and_(*where_clause))
        .select_from(sql.table("ooexpl_wc_input_counts")),
        query_params,
    ).fetchone()
    total_count = row[0]

    s = (
        select(
            [
                sql.text("input"),
                sql.text("SUM(anomaly_count) as anomaly_count"),
                sql.text("SUM(confirmed_count) as confirmed_count"),
                sql.text("SUM(failure_count) as failure_count"),
                sql.text("SUM(total_count) as total_count"),
            ]
        )
        .where(and_(*where_clause))
        .group_by(sql.text("input"))
        .order_by(
            sql.text(
                "confirmed_count DESC, total_count DESC, anomaly_count DESC, input ASC"
            )
        )
        .limit(int(limit))
        .offset(int(offset))
        .select_from(sql.table("ooexpl_wc_input_counts"))
    )

    current_page = math.ceil(offset / limit) + 1
    metadata = {
        "offset": offset,
        "limit": limit,
        "current_page": current_page,
        "total_count": total_count,
        "next_url": None,
    }
    results = []
    q = current_app.db_session.execute(s, query_params)
    for input, anomaly_count, confirmed_count, failure_count, total_count in q:
        results.append(
            {
                "input": input,
                "anomaly_count": int(anomaly_count),
                "confirmed_count": int(confirmed_count),
                "failure_count": int(failure_count),
                "total_count": int(total_count),
            }
        )

    if len(results) >= limit:
        next_args = request.args.to_dict()
        next_args["offset"] = "%s" % (offset + limit)
        next_args["limit"] = "%s" % limit
        next_url = urljoin(
            current_app.config["BASE_URL"],
            "/api/_/website_urls?%s" % urlencode(next_args),
        )
        metadata["next_url"] = next_url

    return jsonify({"metadata": metadata, "results": results})


@api_private_blueprint.route("/vanilla_tor_stats", methods=["GET"])
def api_private_vanilla_tor_stats():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing probe_cc")
    s = sql.text(
        """SELECT
	vt.probe_asn,
	MAX(vt.measurement_start_time) as last_tested,
	AVG(
	GREATEST(
		LEAST(vt.test_runtime, vt.timeout),
		0
	)) AS test_runtime_avg, -- I do this to overcome some bugs in few measurements that have a very high runtime or a negative runtime
  MIN(vt.test_runtime) AS test_runtime_min,
  MAX(vt.test_runtime) AS test_runtime_max,
  COUNT(CASE WHEN vt.success = true THEN 1 END) as success_count,
  COUNT(CASE WHEN vt.success = false THEN 1 END) as failure_count,
  COUNT(*) as total_count
FROM (
	SELECT
	  measurement.msm_no,
	  report.probe_cc,
	  report.probe_asn,
	  measurement.measurement_start_time,
	  measurement.test_runtime,
	  vanilla_tor.timeout,
	  vanilla_tor.success
	FROM report
	JOIN measurement ON report.report_no = measurement.report_no
	JOIN vanilla_tor ON vanilla_tor.msm_no = measurement.msm_no
	WHERE measurement_start_time > (now() - interval '6 months')
	AND test_name = 'vanilla_tor'
	AND probe_cc = :probe_cc
) as vt
GROUP BY 1;"""
    )

    # This is the minimum number of tests to consider a result noteworthy
    MIN_TESTS = 5
    ANOMALY_PERC = 0.6

    results = {"networks": [], "notok_networks": 0}
    q = current_app.db_session.execute(s, {"probe_cc": probe_cc})
    for row in q:
        (
            probe_asn,
            last_tested,
            test_runtime_avg,
            test_runtime_min,
            test_runtime_max,
            success_count,
            failure_count,
            total_count,
        ) = row

        results["last_tested"] = results.get("last_tested", last_tested)
        if results["last_tested"] < last_tested:
            results["last_tested"] = last_tested
        if total_count > 5 and float(success_count) / float(total_count) < ANOMALY_PERC:
            results["notok_networks"] += 1

        results["networks"].append(
            {
                "probe_asn": probe_asn,
                "last_tested": last_tested,
                "test_runtime_avg": test_runtime_avg,
                "test_runtime_min": test_runtime_min,
                "test_runtime_max": test_runtime_max,
                "success_count": success_count,
                "failure_count": failure_count,
                "total_count": total_count,
            }
        )
    return jsonify(results)


@api_private_blueprint.route("/im_networks", methods=["GET"])
def api_private_im_networks():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing probe_cc")

    test_names = [
        sql.literal_column("test_name") == tg_name for tg_name in TEST_GROUPS["im"]
    ]
    s = (
        select(
            [
                sql.text("SUM(count) as msm_count"),
                sql.text("MAX(test_day)"),
                sql.text("probe_asn"),
                sql.text("test_name"),
            ]
        )
        .where(
            and_(
                sql.text("test_day >= current_date - interval '31 day'"),
                # We exclude the last day to wait for the pipeline
                sql.text("test_day < current_date"),
                sql.text("probe_cc = :probe_cc"),
                or_(*test_names),
            )
        )
        .group_by(sql.text("test_name, probe_asn"))
        .order_by(sql.text("test_name, msm_count DESC"))
        .select_from(sql.table("ooexpl_daily_msm_count"))
    )

    results = {}
    q = current_app.db_session.execute(s, {"probe_cc": probe_cc})
    for msm_count, last_tested, probe_asn, test_name in q:
        results[test_name] = results.get(
            test_name,
            {"anomaly_networks": [], "ok_networks": [], "last_tested": last_tested},
        )
        results[test_name]["ok_networks"].append(
            {
                "asn": probe_asn,
                "name": "",
                "total_count": msm_count,
                "last_tested": last_tested,
            }
        )
        if results[test_name]["last_tested"] < last_tested:
            results[test_name]["last_tested"] = last_tested

    return jsonify(results)


@api_private_blueprint.route("/im_stats", methods=["GET"])
def api_private_im_stats():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    test_name = request.args.get("test_name")
    if not test_name or test_name not in TEST_GROUPS["im"]:
        raise BadRequest("invalid test_name")

    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing probe_cc")

    probe_asn = request.args.get("probe_asn")
    if probe_asn is None:
        raise BadRequest("missing probe_asn")
    probe_asn = int(probe_asn.replace("AS", ""))

    s = sql.text(
        """SELECT COALESCE(count, 0), d.test_day
FROM (
(
	SELECT
	date_trunc('day', (current_date - offs)) AS test_day
	FROM generate_series(0, 31, 1) AS offs
) d
LEFT OUTER JOIN
(
	SELECT
	SUM(count) as count,
	test_day
	FROM ooexpl_daily_msm_count
	WHERE
    probe_cc = :probe_cc
    AND test_name = :test_name
    AND probe_asn = :probe_asn
	AND test_day >= current_date - interval '31 day'
	AND test_day < current_date
	GROUP BY test_day
) m
ON d.test_day = m.test_day
)
ORDER BY test_day;"""
    )

    query_params = {
        "probe_cc": probe_cc,
        "probe_asn": probe_asn,
        "test_name": test_name,
    }

    results = []
    q = current_app.db_session.execute(s, query_params)
    for count, test_day in q:
        results.append(
            {"test_day": test_day, "total_count": count, "anomaly_count": None}
        )

    return jsonify({"results": results})


@api_private_blueprint.route("/network_stats", methods=["GET"])
def api_private_network_stats():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing probe_cc")

    limit = int(request.args.get("limit", 10))
    if limit <= 0:
        limit = 10
    offset = int(request.args.get("offset", 0))

    row = current_app.db_session.execute(
        select([sql.text("COUNT(DISTINCT probe_asn)")])
        .where(and_(sql.text("probe_cc = :probe_cc")))
        .select_from(sql.table("ooexpl_netinfo")),
        {"probe_cc": probe_cc},
    ).fetchone()
    total_count = row[0]

    s = (
        select(
            [
                sql.text("client_asn_name"),
                sql.text("probe_asn"),
                sql.text("count"),
                sql.text("download_speed_mbps_median"),
                sql.text("upload_speed_mbps_median"),
                sql.text("rtt_avg"),
            ]
        )
        .where(and_(sql.text("probe_cc = :probe_cc")))
        .order_by(sql.text("count DESC"))
        .limit(limit)
        .offset(offset)
        .select_from(sql.table("ooexpl_netinfo"))
    )

    current_page = math.ceil(offset / limit) + 1
    metadata = {
        "offset": offset,
        "limit": limit,
        "current_page": current_page,
        "total_count": total_count,
        "next_url": None,
    }
    results = []
    q = current_app.db_session.execute(s, {"probe_cc": probe_cc})
    for asn_name, asn, msm_count, download, upload, rtt in q:
        results.append(
            {
                "asn_name": asn_name,
                "asn": asn,
                "msm_count": msm_count,
                "download_speed_mbps_median": download,
                "upload_speed_mbps_median": upload,
                "rtt_avg": rtt,
                "middlebox_detected": None,
            }
        )

    if len(results) >= limit:
        next_args = request.args.to_dict()
        next_args["offset"] = "%s" % (offset + limit)
        next_args["limit"] = "%s" % limit
        next_url = urljoin(
            current_app.config["BASE_URL"],
            "/api/_/network_stats?%s" % urlencode(next_args),
        )
        metadata["next_url"] = next_url

    return jsonify({"metadata": metadata, "results": results})


@api_private_blueprint.route("/country_overview", methods=["GET"])
def api_private_country_overview():
    """TODO
    ---
    responses:
      '200':
        description: TODO
    """
    probe_cc = request.args.get("probe_cc")
    if probe_cc is None or len(probe_cc) != 2:
        raise BadRequest("missing or incorrect probe_cc")

    # FIXME
    return jsonify(
        {
            "circumvention_tools_blocked": None,
            "first_bucket_date": "2013-10-29",
            "im_apps_blocked": None,
            "measurement_count": 6652155,
            "middlebox_detected_networks": None,
            "network_count": 333,
            "websites_confirmed_blocked": 3,
        }
    )

    # row = current_app.db_session.execute(
    #     select([sql.text("COUNT(DISTINCT input)")])
    #     .where(
    #         and_(
    #             sql.text("confirmed_count > 0"),
    #             sql.text("probe_cc = :probe_cc"),
    #             sql.text("test_day >= current_date - interval '31 day'"),
    #         )
    #     )
    #     .select_from(sql.table("ooexpl_wc_input_counts")),
    #     {"probe_cc": probe_cc},
    # ).fetchone()
    # websites_confirmed_blocked = row[0]
    #
    # "COUNT(DISTINCT input)   confirmed_count > 0"
    # probe_cc = :probe_cc"),
    # test_day >= current_date - interval '31 day'"),
    # ).fetchone()
    # websites_confirmed_blocked = row[0]

    # row = current_app.db_session.execute(
    #    select([sql.text("SUM(count)"), sql.text("COUNT(DISTINCT probe_asn)")])
    #    .where(and_(sql.text("probe_cc = :probe_cc")))
    #    .select_from(sql.table("ooexpl_bucket_msm_count")),
    #    {"probe_cc": probe_cc},
    # ).fetchone()
    # measurement_count = row[0]
    # network_count = row[1]

    # row = current_app.db_session.execute(
    #    select([sql.text("bucket_date")])
    #    .where(and_(sql.text("probe_cc = :probe_cc")))
    #    .select_from(sql.table("ooexpl_bucket_msm_count"))
    #    .order_by(sql.text("bucket_date ASC"))
    #    .limit(1),
    #    {"probe_cc": probe_cc},
    # ).fetchone()
    # first_bucket_date = None
    # if row:
    #    first_bucket_date = row[0]

    # return jsonify(
    #    {
    #        "websites_confirmed_blocked": websites_confirmed_blocked,
    #        "middlebox_detected_networks": None,
    #        "im_apps_blocked": None,
    #        "circumvention_tools_blocked": None,
    #        "measurement_count": measurement_count,
    #        "network_count": network_count,
    #        "first_bucket_date": first_bucket_date,
    #    }
    # )


@api_private_blueprint.route("/global_overview", methods=["GET"])
def api_private_global_overview():
    """Provide global summary of measurements
    Sources: global_stats db table
    ---
    responses:
      '200':
        description: JSON struct TODO
    """
    q = select([sql.text("*")]).select_from(sql.table("global_stats"))
    r = current_app.db_session.execute(q).fetchone()
    return cachedjson(24, **dict(r))


@api_private_blueprint.route("/global_overview_by_month", methods=["GET"])
def api_private_global_by_month():
    """Provide global summary of measurements
    Sources: global_by_month db table
    ---
    responses:
      '200':
        description: JSON struct TODO
    """
    q = select(
        [
            sql.text("countries_by_month"),
            sql.text("networks_by_month"),
            sql.text("measurements_by_month"),
            sql.text("month"),
        ]
    ).select_from(sql.table("global_by_month"))
    rows = current_app.db_session.execute(q).fetchall()
    n = [{"date": r[3], "value": r[0]} for r in rows]
    c = [{"date": r[3], "value": r[1]} for r in rows]
    m = [{"date": r[3], "value": r[2]} for r in rows]
    return cachedjson(
        24, networks_by_month=n, countries_by_month=c, measurements_by_month=m
    )
