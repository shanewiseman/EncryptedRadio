#!/usr/bin/env python3
"""Check or explicitly apply the repository's GitHub policy using the REST API."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API_VERSION = "2026-03-10"


class PolicyError(Exception):
    """A policy cannot be safely checked or applied."""


class APIError(PolicyError):
    """An API request failed without exposing credentials or response bodies."""

    def __init__(self, method, path, status):
        self.status = status
        super().__init__(f"GitHub {method} {path} failed (HTTP {status}). "
                         "Check repository access, token permissions, and plan support.")


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward the Authorization header to a redirected endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubAPI:
    def __init__(self, token):
        # urllib may echo invalid header values in an exception. Reject malformed
        # credentials before constructing Authorization, without printing them.
        if not isinstance(token, str) or not token or any(
            not 33 <= ord(character) <= 126 for character in token
        ):
            raise PolicyError("GitHub token must be a single nonempty ASCII value "
                              "without whitespace or control characters.")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirects())

    def request(self, method, path, data=None):
        if not path.startswith("/") or path.startswith("//"):
            raise PolicyError("Expected an absolute GitHub API path.")
        request = urllib.request.Request(
            "https://api.github.com" + path,
            data=None if data is None else json.dumps(data).encode("utf-8"),
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "EncryptedRadio-repository-policy",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            raise APIError(method, path, error.code) from None
        except (urllib.error.URLError, TimeoutError):
            raise PolicyError("Unable to reach the GitHub API.") from None


def get_token():
    for variable in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(variable, "").strip():
            return os.environ[variable].strip()
    if shutil.which("gh"):
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            capture_output=True, text=True, check=False, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise PolicyError("Authenticate with `gh auth login`, or provide GH_TOKEN/GITHUB_TOKEN "
                      "with repository Administration: write. No credentials were found.")


def load_policy(root=ROOT):
    config = json.loads((root / ".github/repository.json").read_text())
    rulesets = [json.loads(path.read_text())
                for path in sorted((root / ".github/rulesets").glob("*.json"))]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config["repository"]):
        raise PolicyError("repository must be an owner/name pair.")
    names = [ruleset["name"] for ruleset in rulesets]
    if not names or len(names) != len(set(names)):
        raise PolicyError("Policy must contain uniquely named rulesets.")
    return config, rulesets


def matches(expected, actual):
    """Compare managed keys; ignore server metadata and array order, not extra actors."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        remaining = list(actual)
        for item in expected:
            for index, candidate in enumerate(remaining):
                if matches(item, candidate):
                    remaining.pop(index)
                    break
            else:
                return False
        return True
    return type(expected) is type(actual) and expected == actual


def read_state(api, config, rulesets):
    """Read all managed state before writes; reject wrong owners and ambiguous names."""
    base = "/repos/" + config["repository"]
    repository = api.request("GET", base)
    if repository["full_name"].lower() != config["repository"].lower():
        raise PolicyError("Repository identity differs from .github/repository.json.")
    owner = repository["owner"]
    if owner["type"] != "User" or owner["id"] != config["owner_user_id"]:
        raise PolicyError("Repository owner differs from the configured personal account.")
    if not repository.get("permissions", {}).get("admin", False):
        raise PolicyError("Administrator access is required to verify bypass actors and settings.")
    branch = urllib.parse.quote(config["settings"]["default_branch"], safe="")
    try:
        api.request("GET", f"{base}/branches/{branch}")
    except APIError as error:
        if error.status == 404:
            raise PolicyError("Create and push the initial master branch before applying policy.") from None
        raise

    state = {
        "repository": repository,
        "actions_permissions": api.request("GET", base + "/actions/permissions"),
        "workflow_permissions": api.request("GET", base + "/actions/permissions/workflow"),
        "rulesets": {},
    }
    try:
        api.request("GET", base + "/vulnerability-alerts")
        state["vulnerability_alerts"] = True
    except APIError as error:
        if error.status != 404:
            raise
        state["vulnerability_alerts"] = False
    if not repository["private"]:
        state["private_vulnerability_reporting"] = api.request(
            "GET", base + "/private-vulnerability-reporting"
        )["enabled"]

    wanted_names = {ruleset["name"] for ruleset in rulesets}
    page = 1
    while True:
        listing = api.request("GET", f"{base}/rulesets?includes_parents=false&per_page=100&page={page}")
        for summary in listing:
            name = summary["name"]
            if name not in wanted_names:
                continue
            if name in state["rulesets"]:
                raise PolicyError(f"Multiple repository rulesets named {name}; resolve the ambiguity first.")
            detail = api.request("GET", f"{base}/rulesets/{summary['id']}")
            if "bypass_actors" not in detail:
                raise PolicyError("GitHub omitted bypass actors; a token with Administration: write is required.")
            state["rulesets"][name] = detail
        if len(listing) < 100:
            break
        page += 1
    return state


def changes(config, rulesets, state):
    """Return a plan of (label, method, path, payload) tuples."""
    base = "/repos/" + config["repository"]
    plan = []
    for key, method, path in (
        ("settings", "PATCH", base),
        ("actions_permissions", "PUT", base + "/actions/permissions"),
        ("workflow_permissions", "PUT", base + "/actions/permissions/workflow"),
    ):
        actual = state["repository"] if key == "settings" else state[key]
        if not matches(config[key], actual):
            plan.append((key, method, path, config[key]))
    security = config["security"]
    if security["vulnerability_alerts"] != state["vulnerability_alerts"]:
        method = "PUT" if security["vulnerability_alerts"] else "DELETE"
        plan.append(("vulnerability_alerts", method, base + "/vulnerability-alerts", None))
    if not state["repository"]["private"]:
        desired = security["private_vulnerability_reporting_for_public_repositories"]
        if desired != state["private_vulnerability_reporting"]:
            method = "PUT" if desired else "DELETE"
            plan.append(("private_vulnerability_reporting", method,
                         base + "/private-vulnerability-reporting", None))
    for ruleset in rulesets:
        current = state["rulesets"].get(ruleset["name"])
        if current is None:
            plan.append((ruleset["name"], "POST", base + "/rulesets", ruleset))
        elif not matches(ruleset, current):
            plan.append((ruleset["name"], "PUT", f"{base}/rulesets/{current['id']}", ruleset))
    return plan


def reconcile(api, config, rulesets, apply=False):
    state = read_state(api, config, rulesets)
    plan = changes(config, rulesets, state)
    if state["repository"]["private"]:
        print("Private vulnerability reporting: not applicable to a private repository.")
    if not plan:
        print("GitHub policy matches the managed configuration.")
        return 0
    for label, method, path, payload in plan:
        print(f"{'Apply' if apply else 'Drift'}: {label}")
    if not apply:
        print("Read-only check. Run with --apply to apply the reviewed configuration.")
        return 1
    for label, method, path, payload in plan:
        api.request(method, path, payload)
    remaining = changes(config, rulesets, read_state(api, config, rulesets))
    if remaining:
        raise PolicyError("GitHub did not retain all requested settings: "
                          + ", ".join(item[0] for item in remaining))
    print("Applied and verified GitHub policy.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="read-only drift check (default)")
    mode.add_argument("--apply", action="store_true", help="write managed settings and verify them")
    args = parser.parse_args(argv)
    try:
        config, rulesets = load_policy()
        return reconcile(GitHubAPI(get_token()), config, rulesets, apply=args.apply)
    except (PolicyError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(f"Error: {error}", file=sys.stderr)
        if args.apply:
            print("Writes are not transactional; check remote state before retrying.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
