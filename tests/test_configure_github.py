"""Offline tests for safe, idempotent GitHub policy reconciliation."""

from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/configure_github.py"
SPEC = importlib.util.spec_from_file_location("configure_github", SCRIPT)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class FakeAPI:
    """Model only the endpoints used by the reconciler, without network access."""

    def __init__(self, config, rulesets):
        self.base = "/repos/" + config["repository"]
        self.repository = {
            **deepcopy(config["settings"]),
            "full_name": config["repository"],
            "owner": {"id": config["owner_user_id"], "type": "User"},
            "private": False,
            "permissions": {"admin": True},
        }
        self.actions = deepcopy(config["actions_permissions"])
        self.workflow = deepcopy(config["workflow_permissions"])
        self.alerts = config["security"]["vulnerability_alerts"]
        self.reporting = config["security"]["private_vulnerability_reporting_for_public_repositories"]
        self.rulesets = {index: {**deepcopy(rule), "id": index, "source_type": "Repository"}
                        for index, rule in enumerate(rulesets, start=1)}
        self.calls = []
        self.branch_exists = True
        self.ignore_writes = False

    def request(self, method, path, data=None):
        self.calls.append((method, path, deepcopy(data)))
        route = path.removeprefix(self.base)
        if method != "GET" and self.ignore_writes:
            return None
        if route == "":
            if method == "PATCH":
                self.repository.update(deepcopy(data))
            return deepcopy(self.repository)
        if route.startswith("/branches/"):
            if not self.branch_exists:
                raise policy.APIError(method, path, 404)
            return {"name": "master"}
        if route in ("/actions/permissions", "/actions/permissions/workflow"):
            target = self.actions if route == "/actions/permissions" else self.workflow
            if method == "PUT":
                target.update(deepcopy(data))
            return deepcopy(target)
        if route == "/vulnerability-alerts":
            if method != "GET":
                self.alerts = method == "PUT"
            if method == "GET" and not self.alerts:
                raise policy.APIError(method, path, 404)
            return None
        if route == "/private-vulnerability-reporting":
            if method != "GET":
                self.reporting = method == "PUT"
            return {"enabled": self.reporting}
        if route.startswith("/rulesets?"):
            page = int(route.rsplit("page=", 1)[1])
            records = list(self.rulesets.values())[(page - 1) * 100:page * 100]
            return [{"id": rule["id"], "name": rule["name"]} for rule in records]
        if route == "/rulesets" and method == "POST":
            rule_id = max(self.rulesets, default=0) + 1
            self.rulesets[rule_id] = {**deepcopy(data), "id": rule_id}
            return deepcopy(self.rulesets[rule_id])
        if route.startswith("/rulesets/"):
            rule_id = int(route.rsplit("/", 1)[1])
            if method == "PUT":
                self.rulesets[rule_id] = {**deepcopy(data), "id": rule_id}
            return deepcopy(self.rulesets[rule_id])
        raise AssertionError(f"Unexpected request: {method} {route}")

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]


class GitHubPolicyTests(unittest.TestCase):
    def setUp(self):
        self.config, self.rulesets = policy.load_policy()
        self.api = FakeAPI(self.config, self.rulesets)

    def run_policy(self, apply=False):
        with redirect_stdout(io.StringIO()):
            return policy.reconcile(self.api, self.config, self.rulesets, apply=apply)

    def test_check_reports_drift_without_writes(self):
        self.api.repository["allow_merge_commit"] = True
        self.api.alerts = False
        self.assertEqual(self.run_policy(), 1)
        self.assertEqual(self.api.writes, [])

    def test_apply_repairs_all_drift_and_second_apply_is_noop(self):
        self.api.repository["allow_merge_commit"] = True
        self.api.actions["sha_pinning_required"] = False
        self.api.workflow["can_approve_pull_request_reviews"] = True
        self.api.alerts = False
        self.api.reporting = False
        self.api.rulesets = {}
        self.assertEqual(self.run_policy(apply=True), 0)
        self.assertEqual(len(self.api.writes), 7)
        self.api.calls.clear()
        self.assertEqual(self.run_policy(apply=True), 0)
        self.assertEqual(self.api.writes, [])

    def test_update_uses_existing_id_and_preserves_unrelated_ruleset(self):
        self.api.rulesets[1]["enforcement"] = "disabled"
        unrelated = {"id": 999, "name": "another-policy", "enforcement": "active"}
        self.api.rulesets[999] = deepcopy(unrelated)
        self.assertEqual(self.run_policy(apply=True), 0)
        self.assertEqual(self.api.writes[0][0:2], ("PUT", self.api.base + "/rulesets/1"))
        self.assertEqual(self.api.rulesets[999], unrelated)

    def test_pagination_finds_managed_rulesets_after_first_page(self):
        managed = deepcopy(self.api.rulesets)
        self.api.rulesets = {index: {"id": index, "name": f"unrelated-{index}"}
                            for index in range(10, 110)}
        self.api.rulesets.update(managed)
        self.assertEqual(self.run_policy(), 0)
        self.assertTrue(any("page=2" in call[1] for call in self.api.calls))

    def test_duplicate_managed_names_abort_before_writes(self):
        self.api.rulesets[777] = {**deepcopy(self.api.rulesets[1]), "id": 777}
        with self.assertRaisesRegex(policy.PolicyError, "Multiple repository rulesets"):
            self.run_policy(apply=True)
        self.assertEqual(self.api.writes, [])

    def test_owner_mismatch_aborts_before_writes(self):
        self.api.repository["owner"]["id"] = 999
        with self.assertRaisesRegex(policy.PolicyError, "owner differs"):
            self.run_policy(apply=True)
        self.assertEqual(self.api.writes, [])

    def test_missing_master_aborts_before_writes(self):
        self.api.branch_exists = False
        with self.assertRaisesRegex(policy.PolicyError, "initial master branch"):
            self.run_policy(apply=True)
        self.assertEqual(self.api.writes, [])

    def test_hidden_bypass_actors_abort_instead_of_assuming_no_bypass(self):
        del self.api.rulesets[1]["bypass_actors"]
        with self.assertRaisesRegex(policy.PolicyError, "omitted bypass actors"):
            self.run_policy(apply=True)
        self.assertEqual(self.api.writes, [])

    def test_extra_bypass_actor_is_drift_even_with_server_metadata(self):
        self.api.rulesets[1]["bypass_actors"].append({
            "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"
        })
        self.assertEqual(self.run_policy(), 1)
        self.assertEqual(self.api.writes, [])

    def test_rule_order_and_server_default_parameters_are_ignored(self):
        for ruleset in self.api.rulesets.values():
            ruleset["rules"].reverse()
            for rule in ruleset["rules"]:
                rule.setdefault("parameters", {})["server_default"] = False
        self.assertEqual(self.run_policy(), 0)

    def test_failed_postwrite_verification_is_not_success(self):
        self.api.repository["allow_merge_commit"] = True
        self.api.ignore_writes = True
        with self.assertRaisesRegex(policy.PolicyError, "did not retain"):
            self.run_policy(apply=True)

    def test_private_repo_skips_public_only_reporting(self):
        self.api.repository["private"] = True
        self.assertEqual(self.run_policy(), 0)
        self.assertFalse(any("private-vulnerability-reporting" in call[1]
                             for call in self.api.calls))

    def test_api_errors_do_not_include_token_or_response_body(self):
        error = policy.APIError("GET", "/repos/example/project", 403)
        self.assertIn("HTTP 403", str(error))
        self.assertNotIn("Authorization", str(error))

    def test_malformed_tokens_fail_before_header_construction_without_echoing_token(self):
        for token in ("fake-token\nsecond-line", "fake-token with-space", "fake-token\x00", ""):
            with self.subTest(token_shape=bool(token)):
                with self.assertRaises(policy.PolicyError) as error:
                    policy.GitHubAPI(token)
                self.assertNotIn("fake-token", str(error.exception))

    def test_redirects_are_not_followed(self):
        self.assertIsNone(policy.NoRedirects().redirect_request(
            None, None, 302, "Found", {}, "https://example.invalid"
        ))


if __name__ == "__main__":
    unittest.main()
