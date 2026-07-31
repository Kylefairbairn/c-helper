#!/usr/bin/env python3
"""Trigger a parameterized Jenkins Pipeline from the command line."""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JenkinsConfig:
    base_url: str
    job_name: str
    username: str
    api_token: str
    verify_tls: bool = True
    timeout: float = 30.0


def add_toggle(
    parser: argparse.ArgumentParser,
    name: str,
    *,
    default: bool,
    description: str,
) -> None:
    """Add --name and --no-name command-line switches."""
    destination = name.replace("-", "_")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        f"--{name}",
        dest=destination,
        action="store_true",
        help=f"Enable {description}",
    )
    group.add_argument(
        f"--no-{name}",
        dest=destination,
        action="store_false",
        help=f"Disable {description}",
    )
    parser.set_defaults(**{destination: default})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trigger Jenkins with individually toggleable stages."
    )

    parser.add_argument(
        "--url",
        default=os.getenv("JENKINS_URL"),
        help="Jenkins base URL, or set JENKINS_URL.",
    )
    parser.add_argument(
        "--job",
        default=os.getenv("JENKINS_JOB"),
        help="Job name or folder/job-name, or set JENKINS_JOB.",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("JENKINS_USER"),
        help="Jenkins username, or set JENKINS_USER.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("JENKINS_API_TOKEN"),
        help="Jenkins API token, or set JENKINS_API_TOKEN.",
    )

    add_toggle(parser, "checkout", default=True, description="checkout stage")
    add_toggle(parser, "build", default=True, description="build stage")
    add_toggle(parser, "tests", default=True, description="test stage")
    add_toggle(parser, "deploy", default=False, description="deploy stage")

    parser.add_argument(
        "--environment",
        choices=("development", "staging", "production"),
        default="development",
        help="Deployment target. Default: development.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait until the Jenkins build finishes.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval when --wait is used. Default: 2 seconds.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification for a trusted test Jenkins server.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print parameters without contacting Jenkins.",
    )

    args = parser.parse_args()

    missing = [
        label
        for label, value in (
            ("--url or JENKINS_URL", args.url),
            ("--job or JENKINS_JOB", args.job),
            ("--user or JENKINS_USER", args.user),
            ("--token or JENKINS_API_TOKEN", args.token),
        )
        if not value
    ]
    if missing:
        parser.error("Missing: " + ", ".join(missing))

    if args.poll_interval <= 0:
        parser.error("--poll-interval must be greater than zero")

    return args


class JenkinsClient:
    def __init__(self, config: JenkinsConfig) -> None:
        self.config = config
        credentials = f"{config.username}:{config.api_token}".encode("utf-8")
        self.authorization = "Basic " + base64.b64encode(credentials).decode("ascii")

        self.ssl_context = ssl.create_default_context()
        if not config.verify_tls:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    @staticmethod
    def job_path(job_name: str) -> str:
        parts = [part for part in job_name.strip("/").split("/") if part]
        if not parts:
            raise ValueError("Job name cannot be empty")
        return "/".join(
            f"job/{urllib.parse.quote(part, safe='')}" for part in parts
        )

    def open_request(self, request: urllib.request.Request):
        try:
            return urllib.request.urlopen(
                request,
                timeout=self.config.timeout,
                context=self.ssl_context,
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Jenkins returned HTTP {exc.code} for {request.full_url}\n{body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not connect to Jenkins: {exc.reason}") from exc

    def authenticated_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
    ) -> urllib.request.Request:
        request = urllib.request.Request(url=url, data=data, method=method)
        request.add_header("Authorization", self.authorization)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header(
                "Content-Type", "application/x-www-form-urlencoded"
            )
        return request

    def get_crumb(self) -> tuple[str, str] | None:
        url = f"{self.config.base_url.rstrip('/')}/crumbIssuer/api/json"
        request = self.authenticated_request(url)
        try:
            with self.open_request(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        return payload["crumbRequestField"], payload["crumb"]

    def trigger(self, parameters: dict[str, str]) -> str | None:
        path = self.job_path(self.config.job_name)
        url = (
            f"{self.config.base_url.rstrip('/')}/{path}/buildWithParameters"
        )
        data = urllib.parse.urlencode(parameters).encode("utf-8")
        request = self.authenticated_request(url, method="POST", data=data)

        crumb = self.get_crumb()
        if crumb:
            request.add_header(crumb[0], crumb[1])

        with self.open_request(request) as response:
            return response.headers.get("Location")

    def get_json(self, url: str) -> dict[str, Any]:
        request = self.authenticated_request(url)
        with self.open_request(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def wait_for_build_url(self, queue_url: str, poll_interval: float) -> str:
        api_url = queue_url.rstrip("/") + "/api/json"
        while True:
            item = self.get_json(api_url)
            if item.get("cancelled"):
                raise RuntimeError("The queued build was cancelled")

            executable = item.get("executable")
            if executable and executable.get("url"):
                return str(executable["url"])

            print(item.get("why") or "Waiting in Jenkins queue...", flush=True)
            time.sleep(poll_interval)

    def wait_for_completion(self, build_url: str, poll_interval: float) -> str:
        api_url = build_url.rstrip("/") + "/api/json"
        while True:
            build = self.get_json(api_url)
            if not build.get("building", False):
                return str(build.get("result") or "UNKNOWN")

            print(f"Build #{build.get('number', '?')} is running...", flush=True)
            time.sleep(poll_interval)


def main() -> int:
    args = parse_args()

    parameters = {
        "RUN_CHECKOUT": str(args.checkout).lower(),
        "RUN_BUILD": str(args.build).lower(),
        "RUN_TESTS": str(args.tests).lower(),
        "RUN_DEPLOY": str(args.deploy).lower(),
        "DEPLOY_ENVIRONMENT": args.environment,
    }

    config = JenkinsConfig(
        base_url=args.url.rstrip("/"),
        job_name=args.job,
        username=args.user,
        api_token=args.token,
        verify_tls=not args.insecure,
        timeout=args.timeout,
    )

    print(f"Jenkins: {config.base_url}")
    print(f"Job: {config.job_name}")
    for key, value in parameters.items():
        print(f"{key}={value}")

    if args.dry_run:
        print("Dry run complete; no request was sent.")
        return 0

    client = JenkinsClient(config)

    try:
        queue_url = client.trigger(parameters)
        print("Jenkins accepted the build request.")

        if not queue_url:
            print("No queue URL was returned; the build was triggered.")
            return 0

        print(f"Queue URL: {queue_url}")
        if not args.wait:
            return 0

        build_url = client.wait_for_build_url(queue_url, args.poll_interval)
        print(f"Build URL: {build_url}")

        result = client.wait_for_completion(build_url, args.poll_interval)
        print(f"Result: {result}")
        return 0 if result == "SUCCESS" else 1

    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
