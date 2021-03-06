"""
Integration test for API

Warning: this test runs against a real database
See README.adoc

Lint using:
    black -t py37 -l 100 --fast ooniapi/tests/integ/test_integration.py

Test using:
    pytest-3 -k test_aggregation
"""

from datetime import datetime, timedelta
from hashlib import shake_128
from urllib.parse import urlencode
import time

import pytest
from tests.utils import *

from ooniapi.measurements import FASTPATH_MSM_ID_PREFIX

# The flask app is created in tests/conftest.py



@pytest.fixture()
def fastpath_dup_rid_input(app):
    """
    Access DB directly. Fetch > 1 measurements from fastpath that share the same
    report_id and input
    Returns (rid, input, count)
    """
    # Too slow
    sql = """
    SELECT report_id, input
    from fastpath
    group by report_id, input
    HAVING count(*) > 1
    LIMIT 1
    """
    with app.app_context():
        for row in app.db_session.execute(sql):
            return (row[0], row[1])


@pytest.fixture()
def fastpath_rid_input(app):
    """Access DB directly. Get a fresh msmt
    Returns (rid, input)
    """
    sql = """
    SELECT report_id, input, test_start_time FROM fastpath
    WHERE input IS NOT NULL
    ORDER BY measurement_start_time DESC
    LIMIT 1
    """
    rid, inp, test_start_time = dbquery(app, sql)[0:3]
    assert rid.strip()
    assert inp.strip()

    return (rid, inp, test_start_time)


def dbquery(app, sql, **query_params):
    """Access DB directly, returns row as tuple."""
    with app.app_context():
        q = app.db_session.execute(sql, query_params)
        return q.fetchone()


def api(client, subpath, **kw):
    url = f"/api/v1/{subpath}"
    if kw:
        assert "?" not in url
        url += "?" + urlencode(kw)

    response = client.get(url)
    assert response.status_code == 200
    assert response.is_json
    return response.json


# # rate limiting / quotas # #

@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run") # FIXME
def test_redirects_and_rate_limit_basic(client):
    # Simulate a forwarded client with a different ipaddr
    # In production the API sits behind Nginx
    headers = {"X-Real-IP": "1.2.3.4"}
    limit = 4000
    paths = (
        "/stats",
        "/files",
        "/files/by_date",
        "/api/_/test_names",
        "/api/_/test_names",
    )
    for p in paths:
        resp = client.get(p, headers=headers)
        assert int(resp.headers["X-RateLimit-Remaining"]) < limit


def test_redirects_and_rate_limit_for_explorer(client):
    # Special ipaddr: no rate limiting. No header is set by the server
    headers = {"X-Real-IP": "37.218.242.149"}
    resp = client.get("/stats", headers=headers)
    assert resp.status_code == 301
    assert "X-RateLimit-Remaining" not in resp.headers

    resp = client.get("/stats", headers=headers)
    assert resp.status_code == 301
    assert "X-RateLimit-Remaining" not in resp.headers


def test_redirects_and_rate_limit_spin(client):
    # Simulate a forwarded client with a different ipaddr
    # In production the API sits behind Nginx
    limit = 4000
    headers = {"X-Real-IP": "1.2.3.4"}
    end_time = time.monotonic() + 1.1
    while time.monotonic() < end_time:
        resp = client.get("/stats", headers=headers)
    assert abs(time.monotonic() - end_time) < 0.2
    assert int(resp.headers["X-RateLimit-Remaining"]) == limit - 2


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run") # FIXME
def test_redirects_and_rate_limit_summary(client):
    url = "quotas_summary"
    response = privapi(client, url)
    assert response == []
    response = privapi(client, url)
    assert len(response) == 1
    assert response[0][0] == 127  # first octet from 127.0.0.1
    assert int(response[0][1]) == 3999  # quota remaining in seconds


@pytest.fixture()
def lower_rate_limits(app):
    # Access the rate limiter buckets directly
    limits = app.limiter._limiter._ipaddr_limits
    old, limits[0] = limits[0], 1
    yield
    limits[0] = old


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run") # FIXME
def test_redirects_and_rate_limit_spin_to_zero(client, lower_rate_limits):
    headers = {"X-Real-IP": "1.2.3.4"}
    end_time = time.monotonic() + 2
    while time.monotonic() < end_time:
        resp = client.get("/_/test_names", headers=headers)
        if resp.status_code == 429:
            return  # we reached the limit

    assert 0, "429 was never received"


def test_redirects_and_rate_limit_spin_to_zero_unmetered(client, lower_rate_limits):
    headers = {"X-Real-IP": "1.2.3.4"}
    end_time = time.monotonic() + 2
    while time.monotonic() < end_time:
        resp = client.get("/health", headers=headers)
        assert resp.status_code == 200, "Unmetered page should always work"


# # list_files # #


@pytest.mark.skip(reason="DROP")
def test_list_files_pagination(client):
    url = "files?limit=1&since=2019-12-01&until=2019-12-02"
    ret = api(client, url)
    results = ret["results"]
    assert len(results) == 1
    assert sorted(results[0].keys()) == [
        "download_url",
        "index",
        "probe_asn",
        "probe_cc",
        "test_name",
        "test_start_time",
    ]
    assert ret["metadata"] == {
        "count": 13273,
        "current_page": 1,
        "limit": 1,
        "next_url": "https://api.ooni.io/api/v1/files?limit=1&since=2019-12-01&until=2019-12-02&offset=1",
        "offset": 0,
        "pages": 13273,
    }
    url = "files?limit=1&since=2019-12-01&until=2019-12-02&offset=1"
    ret = api(client, url)
    results = ret["results"]
    assert len(results) == 1
    assert ret["metadata"] == {
        "count": 13273,
        "current_page": 2,
        "limit": 1,
        "next_url": "https://api.ooni.io/api/v1/files?limit=1&since=2019-12-01&until=2019-12-02&offset=2",
        "offset": 1,
        "pages": 13273,
    }


@pytest.mark.skip(reason="DROP")
def test_list_files_asn(client):
    url = "files?limit=1&since=2019-12-01&until=2019-12-02&probe_asn=AS45595"
    results = api(client, url)["results"]
    assert len(results) == 1
    assert results[0]["probe_asn"] == "AS45595"


@pytest.mark.skip(reason="DROP")
def test_list_files_asn_only_number(client):
    url = "files?limit=1&since=2019-12-01&until=2019-12-02&probe_asn=45595"
    results = api(client, url)["results"]
    assert len(results) == 1
    assert results[0]["probe_asn"] == "AS45595"


@pytest.mark.skip(reason="DROP")
def test_list_files_range_cc(client):
    url = "files?limit=1000&since=2019-12-01&until=2019-12-02&probe_cc=IR"
    ret = api(client, url)
    results = ret["results"]
    assert len(results) == 215
    assert ret["metadata"] == {
        "count": 215,
        "current_page": 1,
        "limit": 1000,
        "next_url": None,
        "offset": 0,
        "pages": 1,
    }


@pytest.mark.skip(reason="DROP")
def test_list_files_range_cc_asn(client):
    url = "files?limit=1000&since=2019-12-01&until=2019-12-02&probe_cc=IR&probe_asn=AS44375"
    results = api(client, url)["results"]
    assert len(results) == 7


# # get_measurement_meta # #


def test_get_measurement_meta_basic(client):
    rid = "20201216T050353Z_webconnectivity_VE_21826_n1_wxAHEUDoof21UBss"
    inp = "http://www.theonion.com/"
    response = api(client, f"measurement_meta?report_id={rid}&input={inp}")
    assert response == {
        "anomaly": False,
        "confirmed": False,
        "failure": False,
        "input": inp,
        "measurement_start_time": "2020-12-16T05:44:41Z",
        "measurement_uid": "20201216054344.884408_VE_webconnectivity_a255255d74fff0be",
        "probe_asn": 21826,
        "probe_cc": "VE",
        "report_id": rid,
        "scores": '{"blocking_general":0.0,"blocking_global":0.0,"blocking_country":0.0,"blocking_isp":0.0,"blocking_local":0.0}',
        "test_name": "web_connectivity",
        "test_start_time": "2020-12-16T05:03:48Z",
        "category_code": "CULTR",
    }
    # TODO
    # "platform": None,
    # "software_name": "ooniprobe-android",
    # "software_version": "2.2.0"
    # "analysis": {"blocking": "http-diff",},
    # "network_name": "Fidget Unlimited",


def test_get_measurement_meta_invalid_rid(client):
    response = client.get(f"/api/v1/measurement_meta?report_id=BOGUS")
    assert b"Invalid report_id" in response.data


def test_get_measurement_meta_not_found(client):
    url = "/api/v1/measurement_meta?report_id=20200712T100000Z_AS9999_BOGUSsYKWBS2S0hdzXf7rhUusKfYP5cQM9HwAdZRPmUfroVoCn"
    resp = client.get(url)
    # TODO: is this a bug?
    assert resp.status_code == 200
    assert resp.json == {}


def FIXME_MISSING_MSMT____test_get_measurement_meta_input_none_from_fp(client):
    rid = "20200712T143743Z_AS27775_17Eq6sYKWBS2S0hdzXf7rhUusKfYP5cQM9HwAdZRPmUfroVoCn"
    # input is None
    response = api(client, f"measurement_meta?report_id={rid}")
    assert response == {
        "anomaly": False,
        "category_code": None,
        "confirmed": False,
        "failure": False,
        "fp_measurement_id": "temp-fid-00ae35a61dadc20e014d9d544525b823",
        "input": None,
        "measurement_id": "temp-fid-00ae35a61dadc20e014d9d544525b823",
        "measurement_start_time": "2020-07-20T19:36:23Z",
        "mr_measurement_id": None,
        "platform": "android",
        "probe_asn": 27775,
        "probe_cc": "SR",
        "report_id": rid,
        "scores": "{}",
        "software_name": None,
        "software_version": None,
        "test_name": "ndt",
        "test_start_time": "2020-07-20 19:35:55",
    }


def FIXME_test_get_measurement_meta_input_none_from_fp(client):
    rid = "20200121T235958Z_AS15169_4oH03thuTgTJeZorlWOpDd5rgNAmHoxnb0xfUFbnWxMvc2sfFJ"
    # input is None
    response = api(client, f"measurement_meta?report_id={rid}")
    assert response == {
        "anomaly": False,
        "category_code": None,
        "confirmed": False,
        "failure": False,
        "fp_measurement_id": "temp-fid-00ae35a61dadc20e014d9d544525b823",
        "input": None,
        "measurement_id": "temp-fid-00ae35a61dadc20e014d9d544525b823",
        "measurement_start_time": "2020-07-20T19:36:23Z",
        "mr_measurement_id": None,
        "platform": "android",
        "probe_asn": 27775,
        "probe_cc": "SR",
        "report_id": rid,
        "scores": "{}",
        "software_name": None,
        "software_version": None,
        "test_name": "ndt",
        "test_start_time": "2020-07-20 19:35:55",
    }


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_get_measurement_meta_full(client):
    rid = "20200209T235610Z_AS22773_NqZSA7xdrVbZb6yO25E5a7HM2Zr7ENIwvxEC18a4TpfYOzWxOz"
    inp = "http://www.theonion.com/"
    response = api(client, f"measurement_meta?report_id={rid}&input={inp}&full=True")
    data = response.pop("raw_measurement")
    assert response == {
        "anomaly": False,
        "confirmed": False,
        "failure": False,
        "fp_measurement_id": None,
        "input": inp,
        "measurement_id": "temp-id-381224597",
        "measurement_start_time": "2020-02-09T23:57:26Z",
        "mr_measurement_id": "temp-id-381224597",
        "probe_asn": 22773,
        "probe_cc": "US",
        "report_id": rid,
        "scores": "{}",
        "test_name": "web_connectivity",
        "test_start_time": "2020-02-09T23:56:06Z",
        "platform": None,
        "category_code": "CULTR",
        "software_name": "ooniprobe-android",
        "software_version": "2.2.0",
        "engine_name": "libmeasurement_kit",
        "engine_version": "0.10.6",
        # "analysis": {"blocking": "http-diff",},
        # "network_name": "Fidget Unlimited",
    }
    assert "test_keys" in data


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_get_measurement_meta_full2(client):
    rid = "20200315T031450Z_AS23674_KLMX2GDXaQhaNPGa58tgrGQ6DkKaEGYbaQRG5hLAdEnjVjCMUm"
    inp = "http://www.expressindia.com/"
    response = api(client, f"measurement_meta?report_id={rid}&input={inp}&full=True")
    data = response.pop("data")
    assert response == {
        "anomaly": False,
        "confirmed": False,
        "failure": False,
        "input": inp,
        "measurement_start_time": "2020-03-15T03:37:10Z",
        "probe_asn": 23674,
        "probe_cc": "PK",
        "report_id": rid,
        "scores": '{"blocking_general":0.0,"blocking_global":0.0,"blocking_country":0.0,"blocking_isp":0.0,"blocking_local":0.0}',
        "test_name": "web_connectivity",
        "test_start_time": "2020-03-15T03:14:50Z",
        "category_code": "NEWS",
    }
    assert "test_keys" in data


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_get_measurement_meta_only_in_fp_full(client, fastpath_rid_input):
    rid, inp, test_start_time = fastpath_rid_input
    response = api(client, f"measurement_meta?report_id={rid}&input={inp}&full=True")
    assert response["input"] == inp
    assert response["scores"] != "{}"  # from fastpath
    assert "category_code" in response
    assert "data" in response
    assert "engine_name" in response
    assert "engine_version" in response
    assert "software_name" in response
    assert "software_version" in response


@pytest.mark.slow
@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_get_measurement_meta_duplicate_in_fp(client, fastpath_dup_rid_input):
    rid, inp = fastpath_dup_rid_input
    response = api(client, f"measurement_meta?report_id={rid}&input={inp}")
    # TODO FIXME count duplicates and verify
    assert response["input"] == inp
    assert response["scores"] != "{}"  # from faspath


# This is a msmt from reprocessor.py
@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_get_measurement_meta_full_reprocessed(client):
    rid = "20181030T014439Z_AS10796_ucOhFJsuTvBnUYbJvIaYeMjWe1lxHbfZHuyY9lJp77BXqS7tki"
    inp = "http://del.icio.us"
    response = api(client, f"measurement_meta?report_id={rid}&input={inp}&full=True")
    print(response)
    assert response
    data = response.pop("raw_measurement")
    assert response == {
        "anomaly": False,
        "confirmed": False,
        "failure": False,
        "input": inp,
        "measurement_start_time": "2018-10-30T01:44:47Z",
        "measurement_uid": "00066c98de599500d0ca5a6b83e0154e",
        "probe_asn": 10796,
        "probe_cc": "US",
        "report_id": rid,
        "scores": '{"blocking_general":0.0,"blocking_global":0.0,"blocking_country":0.0,"blocking_isp":0.0,"blocking_local":0.0}',
        "test_name": "web_connectivity",
        "test_start_time": "2018-10-30T01:44:45Z",
        "category_code": None,
        # "analysis": {"blocking": "http-diff",},
        # "network_name": "Fidget Unlimited",
    }
    assert data is not None
    assert "test_keys" in data


# https://explorer.ooni.org/measurement/20210622T144545Z_riseupvpn_MM_133384_n1_VJkB5EObudGDpy9Y
@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_get_raw_measurement_input_null_bug(client):
    # PR#254
    rid = "20210622T144545Z_riseupvpn_MM_133384_n1_VJkB5EObudGDpy9Y"
    r = api(client, f"raw_measurement?report_id={rid}")
    assert "test_keys" in r


# # list_measurements # #


def test_list_measurements_one(client):
    rid = "20201216T050353Z_webconnectivity_VE_21826_n1_wxAHEUDoof21UBss"
    inp = "http://www.theonion.com/"
    response = api(client, f"measurements?report_id={rid}&input={inp}")
    assert response["metadata"]["count"] == 1, jd(response)
    r = response["results"][0]
    assert r == {
        "anomaly": False,
        "confirmed": False,
        "failure": False,
        "input": inp,
        "measurement_start_time": "2020-12-16T05:44:41Z",
        "measurement_url": "https://api.ooni.io/api/v1/raw_measurement?report_id=20201216T050353Z_webconnectivity_VE_21826_n1_wxAHEUDoof21UBss&input=http%3A%2F%2Fwww.theonion.com%2F",
        "probe_asn": "AS21826",
        "probe_cc": "VE",
        "report_id": rid,
        "scores": {
            "blocking_country": 0.0,
            "blocking_general": 0.0,
            "blocking_global": 0.0,
            "blocking_isp": 0.0,
            "blocking_local": 0.0,
        },
        "test_name": "web_connectivity",
    }


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run") # FIXME
def test_list_measurements_search(client):
    # Used by Explorer search
    response = api(
        client,
        f"measurements?domain=www.humanrightsfirst.org&until=2021-07-15&limit=50",
    )
    assert len(response["results"]) == 7, jd(response)


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run") # FIXME
def test_list_measurements_search_cc(client):
    # Used by Explorer search
    response = api(
        client,
        f"measurements?probe_cc=CA&domain=twitter.com&until=2021-07-15&limit=50",
    )
    assert len(response["results"]) == 3, jd(response)


# # Test slow list_measurements queries with order_by = None
#  pytest-3 ooniapi/tests/integ/test_integration.py \
#    -k test_list_measurements_slow --durations=40 -s -x


# These are some of the parameters exposed by Explorer Search
@pytest.mark.timeout(20)
@pytest.mark.parametrize("probe_cc", ("US", None))
@pytest.mark.parametrize("since", ("2021-01-01", None))
@pytest.mark.parametrize("test_name", ("web_connectivity", None))
@pytest.mark.parametrize("anomaly", ("true", None))
@pytest.mark.parametrize("domain", ("twitter.com", None))
@pytest.mark.slow
def test_list_measurements_slow_order_by_complete(
    domain, anomaly, test_name, since, probe_cc, log, client
):
    d = dict(
        probe_cc=probe_cc,
        since=since,
        test_name=test_name,
        anomaly=anomaly,
        domain=domain,
        until="2021-01-10",
    )
    d = {k: v for k, v in d.items() if v is not None}
    url = "measurements?" + urlencode(d)
    response = api(client, url)


@pytest.mark.parametrize(
    "f", ("probe_cc=YT", "probe_asn=AS3352", "test_name=web_connectivity")
)
def test_list_measurements_slow_order_by_group_1(f, log, client):
    # filter on probe_cc or probe_asn or test_name
    # order by --> "test_start_time"
    url = f"measurements?until=2019-01-01&{f}"
    log.info(url)
    response = api(client, url)


@pytest.mark.parametrize("f", ("anomaly=true", "domain=twitter.com"))
def test_list_measurements_slow_order_by_group_2(f, log, client):
    # anomaly or confirmed or failure or input or domain or category_code
    # order by --> "measurement_start_time"
    url = f"measurements?until=2019-01-01&{f}"
    log.info(url)
    response = api(client, url)


# This is the hard case. When mixing one filter that applies to the
# measurements table and one on the results table, there is no way to do
# an order_by that avoids heavy scans


@pytest.mark.parametrize("f1", ("probe_cc=YT", "test_name=web_connectivity"))
@pytest.mark.parametrize("f2", ("anomaly=true", "domain=twitter.com"))
def test_list_measurements_slow_order_by_group_3(f1, f2, log, client):
    url = f"measurements?until=2019-01-01&{f1}&{f2}"
    log.info(url)
    response = api(client, url)


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_list_measurements_duplicate(client):
    # The API is returning only one result
    rid = "20190720T201845Z_AS3352_Rmagvbg0ufqt8Q0kZBa5Hb0gIzfIBCgHb2PTw0VMLIuHn7mmZ4"
    inp = "http://www.linkedin.com/"
    response = api(client, f"measurements?report_id={rid}&input={inp}")
    assert response["metadata"]["count"] == 1, jd(response)


def test_list_measurements_pagination_old(client, log):
    # Ensure answers stay consistent across calls - using old data
    # https://github.com/ooni/api/issues/49
    url = "measurements?probe_cc=RU&test_name=web_connectivity&limit=100&offset=5000&since=2018-12-24&until=2018-12-25"
    j = None
    for n in range(3):
        log.info(f"{'-' * 20} Cycle {n} {'-' * 20}")
        new = api(client, url)
        del new["metadata"]["query_time"]
        if j is not None:
            assert j == new
        j = new


def test_list_measurements_pagination_new(client, log):
    # Ensure answers stay consistent across calls - using fresh data
    # https://github.com/ooni/api/issues/49
    since = (datetime.utcnow().date() - timedelta(days=1)).strftime("%Y-%m-%d")
    until = datetime.utcnow().date().strftime("%Y-%m-%d")
    url = f"measurements?probe_cc=RU&test_name=web_connectivity&limit=100&offset=5000&since={since}&until={until}"
    j = None
    for n in range(3):
        log.info(f"{'-' * 20} Cycle {n} {'-' * 20}")
        new = api(client, url)
        del new["metadata"]["query_time"]
        if j is not None:
            assert j == new
        j = new


def today_range():
    """Return since/until pair to extract fresh fastpath entries"""
    since = datetime.utcnow().date()
    until = since + timedelta(days=1)
    return since, until


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
@pytest.mark.parametrize("anomaly", (True, False))
@pytest.mark.parametrize("confirmed", (True, False))
@pytest.mark.parametrize("failure", (True, False))
def test_list_measurements_filter_flags_fastpath(
    anomaly, confirmed, failure, client, log
):
    """Test filtering by anomaly/confirmed/msm_failure using the cartesian product

    SELECT COUNT(*), anomaly, confirmed, msm_failure AS failure
    FROM fastpath
    WHERE measurement_start_time > '2020-01-13T00:00:00'::timestamp
    AND measurement_start_time <= '2020-01-14T00:00:00'::timestamp
    GROUP BY anomaly, confirmed, failure
    ORDER BY anomaly, confirmed, failure ASC;
      54412 | f       | f         | f
     156477 | f       | f         | t
      18679 | t       | f         | f
       6820 | t       | f         | t
        352 | t       | t         | f
       2637 | t       | t         | t
    """
    since, until = today_range()
    p = (
        f"measurements?since={since}&until={until}&anomaly={anomaly}"
        + f"&confirmed={confirmed}&failure={failure}&limit=100"
    )
    p = p.lower()
    log.info("Calling %s", p)
    response = api(client, p)
    for r in response["results"]:
        assert r["anomaly"] == anomaly, r
        assert r["confirmed"] == confirmed, r
        assert r["failure"] == failure, r

    i = anomaly * 4 + confirmed * 2 + failure * 1
    thresholds = [10, 100, 0, 0, 10, 10, 0, 10]
    assert len(response["results"]) >= thresholds[i]


# Notice: the decorators must be in reversed order
@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
@pytest.mark.parametrize("failure", (True, False))
@pytest.mark.parametrize("confirmed", (True, False))
@pytest.mark.parametrize("anomaly", (True, False))
def test_list_measurements_filter_flags_pipeline(
    anomaly, confirmed, failure, client, log
):
    """Test filtering by anomaly/confirmed/msm_failure using the cartesian product

    COUNT(*), anomaly, confirmed, measurement.exc IS NOT NULL AS failure
    FROM measurement
    WHERE
        measurement.measurement_start_time > '2019-01-01T00:00:00'::timestamp
        AND measurement.measurement_start_time <= '2019-02-01T00:00:00'::timestamp
        GROUP BY anomaly, confirmed, failure
        ORDER BY anomaly, confirmed, failure;
    """

    p = (
        f"measurements?since=2019-01-01&until=2019-02-01&anomaly={anomaly}"
        + f"&confirmed={confirmed}&failure={failure}&limit=100"
    )
    p = p.lower()
    log.info("Calling %s", p)
    response = api(client, p)
    for r in response["results"]:
        assert r["anomaly"] == anomaly, r
        assert r["confirmed"] == confirmed, r
        assert r["failure"] == failure, r

    if (anomaly, confirmed) == (False, True):
        # confirmed implies anomaly
        cnt = 0
    elif (anomaly, confirmed, failure) == (True, True, True):
        cnt = 1
    else:
        cnt = 100

    assert len(response["results"]) == cnt


# FIXME: glitchy on GH CI
@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_list_measurements_probe_asn(client):
    p = "measurements?probe_asn=AS5089&since=2019-12-8&until=2021-12-11&limit=50"
    response = api(client, p)
    assert len(response["results"]) == 50
    for r in response["results"]:
        assert r["probe_asn"] == "AS5089"


@pytest.mark.skip(reason="no way of currently testing this")
def test_list_measurements_failure_true_fastpath(client):
    since = datetime.utcnow().date()
    until = since + timedelta(days=1)
    p = f"measurements?failure=true&since={since}&until={until}&limit=50"
    response = api(client, p)
    assert len(response["results"]) == 50
    for r in response["results"]:
        assert r["failure"] == True, r


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_list_measurements_failure_false_fastpath(client):
    since = datetime.utcnow().date()
    until = since + timedelta(days=1)
    p = f"measurements?failure=false&since={since}&until={until}&limit=50"
    response = api(client, p)
    assert len(response["results"]) == 50
    for r in response["results"]:
        assert r["failure"] == False, r


def notest_list_measurements_paging_1(client):
    url = "measurements?test_name=dnscheck&since=2020-12-03&until=2020-12-05"
    resp = api(client, url)
    meta = resp["metadata"]
    assert meta["count"] == 0
    assert meta["current_page"] == 1
    assert meta["next_url"] == None


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_list_measurements_paging_2(client):
    url = "measurements?test_name=dnscheck&since=2020-12-03&until=2020-12-04"
    for pagenum in range(1, 9):
        resp = api(client, url)
        meta = resp["metadata"]
        if pagenum < 8:
            assert meta["current_page"] == pagenum, url
            assert meta["offset"] == (pagenum - 1) * 100, url
            assert meta["count"] == -1, (url, meta)
            assert meta["next_url"].startswith("https://api.ooni.io/api/v1/")
        else:
            assert meta["current_page"] == pagenum, url
            assert meta["offset"] == 700, url
            assert meta["count"] == 763, (url, meta)  # is this ok?
            assert meta["next_url"] is None
            break

        url = meta["next_url"].split("/", 5)[-1]


## get_measurement ##


@pytest.mark.skip(reason="broken")
def test_get_measurement(client):
    response = api(client, "measurement/temp-id-321045320")
    assert response["measurement_start_time"] == "2019-07-20 11:43:55", jd(response)
    assert response["probe_asn"] == "AS3352"
    assert response["probe_cc"] == "ES"
    assert (
        response["report_filename"]
        == "2019-07-20/20190717T115517Z-ES-AS3352-web_connectivity-20190720T201845Z_AS3352_Rmagvbg0ufqt8Q0kZBa5Hb0gIzfIBCgHb2PTw0VMLIuHn7mmZ4-0.2.0-probe.json"
    )
    assert len(response["test_keys"]["requests"][0]["response"]["body"]) == 72089


def test_get_measurement_missing_pipeline(client):
    url = "measurement/temp-id-999999999999999999"
    response = client.get(f"/api/v1/{url}")
    assert response.status_code == 400


@pytest.mark.get_measurement
@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_get_measurement_2(log, client, fastpath_rid_input):
    """Simulate Explorer behavior
    Get a measurement from the fastpath table
    """
    # Get a real rid/inp directly from the database
    rid, inp, test_start_time = fastpath_rid_input

    # This has collisions with data from the traditional pipeline
    p = f"measurements?report_id={rid}&input={inp}"
    log.info("Calling API on %s", p)
    response = api(client, p)
    assert response["metadata"]["count"] > 0, jd(response)
    assert len(response["results"]) == 1, jd(response)
    pick = response["results"][0]
    url_substr = "measurement/{}".format(FASTPATH_MSM_ID_PREFIX)
    assert url_substr in pick["measurement_url"]
    assert "anomaly" in pick, pick.keys()
    assert pick["scores"] != {}
    assert "blocking_general" in pick["scores"]

    url = pick["measurement_url"]
    relurl = url[27:]
    log.info("Calling API on %r", relurl)
    msm = api(client, relurl)

    # Assure the correct msmt was received
    msm = api(client, relurl)
    for f in ("probe_asn", "probe_cc", "report_id", "input", "test_name"):
        # (measurement_start_time differs in the timezone letter)
        assert msm[f] == pick[f], "%r field: %r != %r" % (f, msm[f], pick[f])


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
@pytest.mark.get_measurement
def test_bug_355_confirmed(client):
    # Use RU to have enough msmt
    p = "measurements?probe_cc=RU&limit=50&confirmed=true&since=2019-12-23&until=2019-12-24"
    response = api(client, p)
    for r in response["results"]:
        assert r["confirmed"] == True, r
    assert len(response["results"]) == 50


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
@pytest.mark.get_measurement
def test_bug_355_anomaly(client):
    p = "measurements?probe_cc=RU&limit=50&anomaly=true&since=2019-12-23&until=2019-12-24"
    response = api(client, p)
    for r in response["results"]:
        assert r["anomaly"] == True, r
    assert len(response["results"]) == 50


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_bug_142_twitter(client):
    # we can assume there's always enough data
    ts = datetime.utcnow().date().strftime("%Y-%m-%d")
    p = "measurements?domain=twitter.com&until=%s&limit=20" % ts
    response = api(client, p)
    rows = tuple(response["results"])
    assert len(rows) == 20
    for r in rows:
        assert "twitter" in r["input"], r


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_bug_278_with_input_none(client):
    url = "measurements?report_id=20190113T202156Z_AS327931_CgoC3KbgM6zKajvIIt1AxxybJ1HbjwwWJjsJnlxy9rpcGY54VH"
    response = api(client, url)
    assert response["metadata"]["count"] == 1, jd(response)
    assert response["results"] == [
        {
            "anomaly": False,
            "confirmed": False,
            "failure": False,
            "input": None,
            "measurement_id": "temp-id-263478291",
            "measurement_start_time": "2019-02-22T20:21:59Z",
            "measurement_url": "https://api.ooni.io/api/v1/measurement/temp-id-263478291",
            "probe_asn": "AS327931",
            "probe_cc": "DZ",
            "report_id": "20190113T202156Z_AS327931_CgoC3KbgM6zKajvIIt1AxxybJ1HbjwwWJjsJnlxy9rpcGY54VH",
            "scores": {},
            "test_name": "ndt",
        }
    ]


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_bug_278_with_input_not_none(client):
    # Fetch web_connectivity by report_id only. Expect 25 hits where input
    # is backfilled from domain_input
    url = "measurements?report_id=20190221T235955Z_AS8346_GMKlfxcvS7Xcy2vPgzmOIxeJXnLdGmWVcZ18vrelaTQ4YDAUHo"
    response = api(client, url)
    assert response["metadata"]["count"] == 25, jd(response)
    for r in response["results"]:
        assert r["input"].startswith("http")


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_bug_list_measurements_anomaly_coalesce(client):
    # list_measurements coalesce was giving priority to mr_table over fastpath
    url = "measurements?report_id=20200222T165239Z_AS24691_5WcQoZyep2HktNd8UvKf1Ka4C3WPyOc9AQP79zoJ7oPgyDwSWh"
    response = api(client, url)
    assert len(response["results"]) == 1
    r = response["results"][0]
    assert r["scores"]["blocking_general"] > 0.5
    assert not r["scores"]["analysis"]["whatsapp_endpoints_accessible"]

    assert not r["confirmed"]
    assert not r["failure"]
    assert r["anomaly"]


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_list_measurements_external_order_by(client):
    # The last order-by on the rows from pipeline + fastpath
    today = datetime.utcnow().date()
    until = today + timedelta(days=1)
    url = f"measurements?until={until}&probe_cc=TR"
    response = api(client, url)
    last = max(r["measurement_start_time"] for r in response["results"])
    # Ensure that the newest msmt is from today (hence fastpath)
    assert last[:10] == str(today)
    assert len(response["results"]) == 100, jd(response)


def test_list_measurements_bug_probe1034(client):
    url = "measurements?report_id=blah"
    r = client.get(f"/api/v1/{url}", headers={"user-agent": "okhttp"})
    assert r.status_code == 200
    assert r.is_json
    response = r.json
    assert "results" in response
    assert len(response["results"]) == 1, repr(response)


def test_slow_inexistent_domain(client):
    # time-unbounded query, filtering by a domain never monitored
    p = "measurements?domain=meow.com&until=2019-12-11&limit=50"
    response = api(client, p)
    rows = tuple(response["results"])
    assert len(rows) == 0


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_slow_domain_unbounded(client):
    # time-unbounded query, filtering by a popular domain
    p = "measurements?domain=twitter.com&until=2019-12-11&limit=50"
    response = api(client, p)
    rows = tuple(response["results"])
    assert rows


@pytest.mark.skipif(not pytest.proddb, reason="use --proddb to run")
def test_slow_domain_bounded(client):
    p = "measurements?domain=twitter.com&since=2019-12-8&until=2019-12-11&limit=50"
    response = api(client, p)
    assert len(response["results"]) == 48


## files_download ##


@pytest.mark.skip(reason="legacy")
def test_files_download_found(client):
    url = "files/download/2019-06-06/20190606T115021Z-IE-AS5466-ndt-20190606T115024Z_AS5466_fBGQoRbWb034yaEVz25JzTTge72KzFhcXValcZmIaQ8HWqy4Y1-0.2.0-probe.json"
    response = client.get(url)
    assert response.status_code == 200
    assert response.is_streamed
    data = response.get_data()
    assert shake_128(data).hexdigest(3) == "3e50c7"


@pytest.mark.skip(reason="legacy")
def test_files_download_found_legacy(client):
    url = "files/download/20190606T115021Z-IE-AS5466-ndt-20190606T115024Z_AS5466_fBGQoRbWb034yaEVz25JzTTge72KzFhcXValcZmIaQ8HWqy4Y1-0.2.0-probe.json"
    response = client.get(url)
    assert response.status_code == 302


@pytest.mark.skip(reason="legacy")
def test_files_download_missing(client):
    url = "files/download/2019-06-06/bogus-probe.json"
    response = client.get(url)
    assert response.status_code == 404


@pytest.mark.skip(reason="legacy")
def test_files_download_missing_legacy(client):
    url = "files/download/without-slash-bogus-probe.json"
    response = client.get(url)
    assert response.status_code == 404


