"""Read-only verification of learner-owned lab evidence.

Checks never receive or store cloud credentials. They fetch a learner-submitted public URL only on
allowlisted AWS hostnames that resolve to public addresses, without redirects and with a small size
cap, or they read a public GitHub repository through the GitHub REST API. Results are controlled codes.
"""

import ipaddress
import json
import re
import socket
import threading
import time
import zlib
from urllib.parse import quote, urlsplit, urlunsplit

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from skillcoach.clients import Budget, ExternalError
from skillcoach.labs import SHARED_PROTECTED, WORKFLOW_PATH, token_blob_shas

LIMIT = 65536
_watch = threading.local()


class Deadline:
    """Hard wall-clock bound for one request once connected: shuts down its sockets so no slow drip
    (status line, headers, chunk framing or compressed body) can outlast the check, since per-read
    timeouts reset on every byte. TCP connect and the TLS handshake are bounded by the connect timeout
    instead (per socket read); for HTTPS only the post-handshake socket is armed, and allowed hosts terminate TLS at AWS
    or GitHub rather than at learner code."""

    def __init__(self, seconds):
        self.sockets, self.fired, self.lock = [], False, threading.Lock()
        self.timer = threading.Timer(max(0.05, seconds), self.fire)
        self.timer.daemon = True

    def arm(self, sock):
        with self.lock:
            self.sockets.append(sock)
            fired = self.fired
        if fired:
            self.close(sock)

    def fire(self):
        with self.lock:
            self.fired = True
            sockets = list(self.sockets)
        for sock in sockets:
            self.close(sock)

    @staticmethod
    def close(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def __enter__(self):
        _watch.current = self
        self.timer.start()
        return self

    def __exit__(self, *args):
        self.timer.cancel()
        _watch.current = None
        return False


class _Watched:
    def _new_conn(self):
        sock = super()._new_conn()
        current = getattr(_watch, "current", None)
        if current is not None:
            current.arm(sock)
        return sock

    def getresponse(self, *args, **kwargs):
        current = getattr(_watch, "current", None)
        if current is not None and self.sock is not None:
            current.arm(self.sock)  # a reused keep-alive connection
        return super().getresponse(*args, **kwargs)


class _WatchedHTTP(_Watched, HTTPConnection):
    pass


class _WatchedHTTPS(_Watched, HTTPSConnection):
    pass


class _WatchedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _WatchedHTTP


class _WatchedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _WatchedHTTPS


class DeadlineAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _WatchedHTTPPool, "https": _WatchedHTTPSPool}


class CheckedSession(requests.Session):
    """Sends exactly one request through the mounted adapter.

    Session.send would run resolve_redirects even with allow_redirects=False, which reads and decodes a
    3xx body in full (no size cap) before the caller can reject the redirect. Environment proxies are
    ignored so the connection goes to the host whose public addresses were checked.
    """

    def request(self, method, url, *, headers=None, timeout=None, stream=True, allow_redirects=False):
        assert allow_redirects is False and stream is True, "Lab checks never follow redirects"
        prepared = self.prepare_request(requests.Request(method, url, headers=headers))
        return self.get_adapter(prepared.url).send(
            prepared, stream=True, timeout=timeout, verify=True, cert=None, proxies={}
        )


def checked_session():
    session = CheckedSession()
    session.trust_env = False
    session.mount("https://", DeadlineAdapter())
    session.mount("http://", DeadlineAdapter())
    return session


class Undecodable(ValueError):
    pass


def decode_body(body, encoding, limit):
    """Decode a size-capped raw body; None means the decoded content exceeds the limit."""
    encoding = (encoding or "").strip().lower()
    if encoding in ("", "identity"):
        return body
    if encoding in ("gzip", "x-gzip"):
        modes = (16 + zlib.MAX_WBITS,)
    elif encoding == "deflate":
        modes = (zlib.MAX_WBITS, -zlib.MAX_WBITS)
    else:
        raise Undecodable(encoding)
    for wbits in modes:
        inflater = zlib.decompressobj(wbits)
        try:
            out = inflater.decompress(body, limit + 1)
        except zlib.error:
            continue
        if len(out) > limit or inflater.unconsumed_tail:
            return None
        if inflater.eof:
            return out
    raise Undecodable(encoding)


BUCKET = r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"
REGION = r"[a-z]{2}(?:-[a-z]+)+-\d"
HOSTS = {
    "s3-presigned": re.compile(rf"(?:{BUCKET}\.)?s3(?:[.-]{REGION}|\.dualstack\.{REGION})?\.amazonaws\.com"),
    "lambda-url": re.compile(rf"[a-z0-9]{{20,40}}\.lambda-url\.{REGION}\.on\.aws"),
    "api-health": re.compile(rf"[a-z0-9]{{10}}\.execute-api\.{REGION}\.amazonaws\.com"),
    "cloudfront": re.compile(r"d[a-z0-9]{12,14}\.cloudfront\.net"),
}
GITHUB = re.compile(
    r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?"
)
CODES = {
    "verified": "Verified.",
    "url_not_allowed": "That link is not an accepted URL for this lab route. Check the lab instructions.",
    "private_address": "That host does not resolve to a public AWS address.",
    "redirect_not_allowed": "The link redirected. Submit the final HTTPS URL directly.",
    "http_status": "The link did not return HTTP 200.",
    "token_missing": "The response did not contain your lab token.",
    "too_large": "The response was larger than the lab check allows.",
    "unsupported_encoding": "The link returned compressed content SkillCoach cannot read. Serve the file uncompressed.",
    "unreachable": "SkillCoach could not reach the link in time. Check it and submit again.",
    "still_public": "The object is readable without a signature. Keep the bucket private and use a presigned URL.",
    "not_signed": "Submit the presigned URL including its X-Amz-Signature query parameters.",
    "not_cloudfront": "The response did not come through CloudFront.",
    "wrong_path": "The API Gateway URL must end with /health.",
    "repo_not_found": "The GitHub repository was not found or is not public.",
    "token_file_missing": "The .skillcoach token file is missing or does not contain exactly your token.",
    "tests_modified": "Protected tests or pinned configuration differ from the template. Restore them.",
    "workflow_modified": "The SkillCoach labs workflow differs from the template. Restore it.",
    "run_missing": "No SkillCoach labs workflow run exists for the latest commit. Push again or run it manually.",
    "run_in_progress": "The workflow is still running. Submit again after it finishes.",
    "run_failed": "The lab job did not pass on the latest commit. Check the Actions log.",
    "github_busy": "GitHub is rate limiting checks right now. Try again later.",
    "cleanup_pending": "The link still serves your token. Delete the resources, then confirm again.",
    "cleanup_mismatch": "That is not the link you verified for this lab.",
    "bucket_exists": "The bucket still exists. Empty and delete it (aws s3 rb), then confirm again.",
    "cleaned": "Cleanup confirmed.",
}


class LabChecker:
    def __init__(self, config, session=None, resolver=None, clock=None, seconds=8):
        self.config = config
        self.session = session or checked_session()
        self.resolver = resolver or socket.getaddrinfo
        self.clock = clock or time.monotonic
        self.seconds = seconds

    def public(self, host):
        try:
            infos = self.resolver(host, 443, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError):
            return "unreachable"
        addresses = {info[4][0] for info in infos}
        if not addresses or any(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
            return "private_address"
        return None

    def fetch(self, url, budget: Budget):
        remaining = budget.remaining()
        seconds = min(self.seconds, remaining / 2)
        deadline = self.clock() + seconds
        try:
            with (
                Deadline(seconds) as watch,
                self.session.request(
                    "GET",
                    url,
                    allow_redirects=False,
                    stream=True,
                    timeout=(min(3, remaining / 3), min(6, remaining / 3)),
                    headers={
                        "User-Agent": "SkillCoach-lab-check/1",
                        "Accept": "*/*",
                        "Accept-Encoding": "identity",
                    },
                ) as response,
            ):
                if 300 <= response.status_code < 400:
                    return response.status_code, {}, None, "redirect_not_allowed"
                try:
                    body = self.read(response, LIMIT, deadline, budget)
                except Undecodable:
                    body = Undecodable
                # A socket shut down by the watchdog can look like a clean end of a chunked body.
                if watch.fired:
                    return 0, {}, None, "unreachable"
                if body is Undecodable:
                    return response.status_code, {}, None, "unsupported_encoding"
                if body is None:
                    return response.status_code, {}, None, "too_large"
                headers = {k.lower(): v for k, v in response.headers.items()}
                return response.status_code, headers, body.decode("utf-8", "replace"), None
        except (requests.RequestException, urllib3.exceptions.HTTPError, OSError):
            return 0, {}, None, "unreachable"

    def read(self, response, limit, deadline, budget):
        # Raw read1 returns after at most one socket read; the Deadline watchdog bounds each read itself.
        body = bytearray()
        while True:
            if self.clock() > deadline:
                raise TimeoutError("lab_check_deadline")
            budget.remaining()
            chunk = response.raw.read1(4096, decode_content=False)
            if not chunk:
                break
            body += chunk
            if len(body) > limit:
                return None
        headers = {k.lower(): v for k, v in response.headers.items()}
        return decode_body(bytes(body), headers.get("content-encoding"), limit)

    @staticmethod
    def parse(kind, url):
        if not isinstance(url, str) or len(url) > 4096 or any(c.isspace() for c in url):
            return None
        parts = urlsplit(url)
        try:
            port = parts.port
        except ValueError:
            return None
        host = (parts.hostname or "").lower()
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or port not in (None, 443)
            or parts.fragment
            or not HOSTS[kind].fullmatch(host)
        ):
            return None
        return parts._replace(netloc=host)

    def aws(self, route, url, token, budget: Budget):
        parts = self.parse(route.kind, url)
        if parts is None:
            return {"code": "url_not_allowed"}
        if route.kind == "s3-presigned" and "x-amz-signature=" not in parts.query.lower():
            return {"code": "not_signed"}
        if route.kind == "api-health" and not parts.path.rstrip("/").endswith("/health"):
            return {"code": "wrong_path"}
        if problem := self.public(parts.hostname):
            return {"code": problem}
        status, headers, body, problem = self.fetch(urlunsplit(parts), budget)
        if problem:
            return {"code": problem, "status": status}
        if status != 200:
            return {"code": "http_status", "status": status}
        if token not in body:
            return {"code": "token_missing"}
        checks = ["https", "public-aws-host", "no-redirect", "token"]
        if route.kind == "cloudfront":
            marker = (headers.get("x-cache", "") + " " + headers.get("via", "")).lower()
            if "cloudfront" not in marker:
                return {"code": "not_cloudfront"}
            checks.append("cloudfront-edge")
        if route.kind == "s3-presigned":
            status, _, body, problem = self.fetch(urlunsplit(parts._replace(query="")), budget)
            if problem == "unreachable":
                return {"code": "unreachable"}
            if status == 200:
                # Any unsigned 200 means the object is readable without a signature, whatever the body.
                return {"code": "still_public"}
            checks.append("unsigned-denied")
        return {"code": "verified", "checks": checks}

    def cleanup(self, route, url, token, budget: Budget):
        parts = self.parse(route.kind, url)
        if parts is None:
            return {"code": "url_not_allowed"}
        problem = self.public(parts.hostname)
        if problem == "unreachable":
            return {"code": "cleaned", "checks": ["dns-removed"]}
        if problem:
            return {"code": problem}
        status, _, body, problem = self.fetch(urlunsplit(parts), budget)
        if problem == "unreachable":
            return {"code": "unreachable"}
        if status == 200 and body and token in body:
            return {"code": "cleanup_pending"}
        if route.kind == "s3-presigned":
            # Anonymous requests get 403 for both existing and missing keys; only NoSuchBucket proves deletion.
            status, _, body, problem = self.fetch(urlunsplit(parts._replace(query="")), budget)
            if problem == "unreachable":
                return {"code": "unreachable"}
            if status == 404 and body and "NoSuchBucket" in body:
                return {"code": "cleaned", "checks": ["bucket-deleted"]}
            return {"code": "bucket_exists"}
        if problem == "redirect_not_allowed" or status in (400, 403, 404, 410):
            return {"code": "cleaned", "checks": ["token-not-served"]}
        return {"code": "unreachable", "status": status}

    def github(self, lab, protected, url, token, budget: Budget):
        match = GITHUB.fullmatch(url) if isinstance(url, str) else None
        if not match or match.group(2) in (".", ".."):
            return {"code": "url_not_allowed"}
        base = f"https://api.github.com/repos/{match.group(1)}/{match.group(2)}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Accept-Encoding": "identity",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SkillCoach-lab-check/1",
        }
        if self.config.labs_github_token:
            # Optional read-only token for higher public-API rate limits; never the dashboard publisher token.
            headers["Authorization"] = "Bearer " + self.config.labs_github_token

        def get(path):
            remaining = budget.remaining()
            seconds = min(self.seconds + 2, remaining / 2)
            deadline = self.clock() + seconds
            try:
                with (
                    Deadline(seconds) as watch,
                    self.session.request(
                        "GET",
                        base + path,
                        headers=headers,
                        allow_redirects=False,
                        stream=True,
                        timeout=(min(3, remaining / 3), min(8, remaining / 3)),
                    ) as response,
                ):
                    if response.status_code == 429 or (
                        response.status_code == 403
                        and (
                            response.headers.get("x-ratelimit-remaining") == "0"
                            or "retry-after" in response.headers
                        )
                    ):
                        raise Stop("github_busy")
                    if response.status_code in (301, 302, 307, 403, 404, 410, 451):
                        raise Stop("repo_not_found")
                    if response.status_code != 200:
                        raise Stop("unreachable")
                    body = self.read(response, 2_000_000, deadline, budget)
                    if watch.fired:
                        raise Stop("unreachable")
                    if body is None:
                        raise Stop("too_large")
                    return json.loads(body)
            except (requests.RequestException, urllib3.exceptions.HTTPError, OSError):
                raise Stop("unreachable") from None
            except ValueError:
                raise Stop("unreachable") from None

        try:
            repo = get("")
            if not isinstance(repo, dict) or repo.get("private") is not False:
                return {"code": "repo_not_found"}
            branch = get("/branches/" + quote(str(repo.get("default_branch", "")), safe=""))
            commit = branch["commit"]["sha"]
            tree_sha = branch["commit"]["commit"]["tree"]["sha"]
            tree = get(f"/git/trees/{quote(tree_sha, safe='')}?recursive=1")
            if tree.get("truncated"):
                return {"code": "too_large"}
            blobs = {e.get("path"): e.get("sha") for e in tree.get("tree", []) if e.get("type") == "blob"}
            for path, sha in protected.items():
                if blobs.get(path) != sha:
                    return {"code": "workflow_modified" if path == WORKFLOW_PATH else "tests_modified"}
            if blobs.get(f".skillcoach/{lab.id}.token") not in token_blob_shas(token):
                return {"code": "token_file_missing"}
            runs = get(f"/actions/runs?head_sha={quote(commit, safe='')}&per_page=30").get(
                "workflow_runs", []
            )
            runs = [
                run
                for run in runs
                if run.get("head_sha") == commit
                and str(run.get("path", "")).split("@")[0] == WORKFLOW_PATH
                and run.get("event") in ("push", "workflow_dispatch")
            ]
            if not runs:
                return {"code": "run_missing"}
            run = max(runs, key=lambda item: (item.get("run_attempt", 1), item.get("id", 0)))
            if run.get("status") != "completed":
                return {"code": "run_in_progress"}
            jobs = get(f"/actions/runs/{int(run['id'])}/jobs?per_page=50").get("jobs", [])
            job = next((j for j in jobs if j.get("name") == f"lab-{lab.id}"), None)
            if not job or job.get("conclusion") != "success":
                return {"code": "run_failed"}
            return {
                "code": "verified",
                "checks": ["public-repo", "protected-files", "token-file", "workflow-success"],
            }
        except Stop as stop:
            return {"code": stop.code}
        except (KeyError, TypeError, AttributeError, ValueError):
            return {"code": "unreachable"}


class Stop(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def message(code):
    return CODES.get(code, "The lab check could not be completed.")


__all__ = ["CODES", "ExternalError", "LabChecker", "SHARED_PROTECTED", "message"]
