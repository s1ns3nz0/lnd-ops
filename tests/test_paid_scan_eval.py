import importlib.util
import importlib.machinery
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).parents[1]
SCENARIOS = ROOT / "tests/eval/scenarios"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_script(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evalrun = load_script("eval_paid_scan_agent", ROOT / "ops/eval-paid-scan-agent")
fixture = load("paid_scan_eval_fixture", ROOT / "agent/paid_scan_eval_fixture.py")
prod = fixture.prod
TENANT = "11111111-1111-4111-8111-111111111111"
ORDER = "22222222-2222-4222-8222-222222222222"
ORDER_ARGS = {"tenant_id": TENANT, "order_id": ORDER}


class FixtureServerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = pathlib.Path(tmp.name, "state")
        self.scen = pathlib.Path(tmp.name, "scen")
        self.plays = pathlib.Path(tmp.name, "plays")
        for d in (self.state, self.scen, self.plays):
            d.mkdir()
        (self.plays / "opencti-l402-funnel.md").write_text("# funnel playbook\n")
        for name, verdict in (("one", "incident"), ("two", "healthy")):
            (self.scen / f"{name}.json").write_text(json.dumps(
                {"question": "q", "tools": {"diagnose_l402_funnel": {"status": "observed", "verdict": verdict}}, "expect": {}}))
        patch = unittest.mock.patch.dict("os.environ", {"STATE_DIR": str(self.state), "SCENARIO_DIR": str(self.scen),
                                                        "PLAYBOOK_DIR": str(self.plays)})
        patch.start()
        self.addCleanup(patch.stop)
        server = ThreadingHTTPServer(("127.0.0.1", 0), fixture.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def rpc(self, method, params=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            body["params"] = params
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/mcp", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        return json.load(urllib.request.urlopen(request, timeout=5))

    def tool(self, name, arguments=None):
        reply = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        return json.loads(reply["result"]["content"][0]["text"])

    def assert_invalid_arguments(self, name, arguments):
        reply = self.rpc("tools/call", {"name": name, "arguments": arguments})["result"]
        self.assertTrue(reply["isError"])
        value = json.loads(reply["content"][0]["text"])
        self.assertEqual((value["status"], value["reason"]), ("error", "invalid_arguments"))
        self.assertNotIn("evil", reply["content"][0]["text"])

    def activate(self, text):
        (self.state / "active").write_text(text)

    def test_tool_schemas_are_the_production_dicts(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        self.assertEqual(tools, [prod.TOOL, prod.WORKLOAD_TOOL, prod.FUNNEL_TOOL, prod.PLAYBOOK_TOOL])

    def test_active_scenario_is_read_per_call(self):
        self.activate("one")
        self.assertEqual(self.tool("diagnose_l402_funnel")["verdict"], "incident")
        self.activate("two")
        self.assertEqual(self.tool("diagnose_l402_funnel")["verdict"], "healthy")

    def test_missing_unknown_invalid_or_absent_tool_is_not_configured(self):
        expected = {"status": "unknown", "reason": "not_configured"}
        self.assertEqual(self.tool("diagnose_l402_funnel"), expected)  # no active file
        for active in ("nope", "../one", "ONE", "one\n../x", "a" * 65):
            self.activate(active)
            self.assertEqual(self.tool("diagnose_l402_funnel"), expected, active)
        self.activate("one")
        self.assertEqual(self.tool("get_opencti_workload_status"), expected)

    def test_get_playbook_delegates_to_real_tool(self):
        self.activate("one")
        result = self.tool("get_playbook", {"name": "opencti-l402-funnel"})
        self.assertEqual(result, prod.get_playbook({"name": "opencti-l402-funnel"}))
        self.assertEqual(result["content"], "# funnel playbook\n")
        self.assert_invalid_arguments("get_playbook", {"name": "../x"})

    def test_order_arguments_validated_but_ignored(self):
        self.activate("two")
        (self.scen / "two.json").write_text(json.dumps({"tools": {"diagnose_paid_order": {"stage": "canned"}}}))
        self.assertEqual(self.tool("diagnose_paid_order", ORDER_ARGS), {"stage": "canned"})
        for bad in ({}, {"tenant_id": TENANT}, {**ORDER_ARGS, "x": 1}, {"tenant_id": "x", "order_id": ORDER}):
            self.assert_invalid_arguments("diagnose_paid_order", bad)
        self.assert_invalid_arguments("diagnose_l402_funnel", {"evil-key-123": 1})
        self.assertIn("error", self.rpc("tools/call", {"name": "other", "arguments": {}}))

    def test_healthz(self):
        reply = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/healthz", timeout=5))
        self.assertEqual(reply["status"], "ready")


class ScenarioFileTests(unittest.TestCase):
    def test_scenarios_are_valid(self):
        files = sorted(SCENARIOS.glob("*.json"))
        self.assertEqual(len(files), 5)
        known = {t["name"] for t in fixture.TOOLS}
        for path in files:
            self.assertRegex(path.stem, r"[a-z0-9-]{1,64}")
            data = json.loads(path.read_text())
            self.assertEqual(set(data), {"question", "tools", "expect"}, path.name)
            self.assertTrue(data["question"].strip())
            self.assertTrue(set(data["tools"]) <= known - {"get_playbook"}, path.name)
            expect = data["expect"]
            self.assertLessEqual({"required_tools", "must_mention", "must_not"}, set(expect), path.name)
            self.assertTrue(set(expect["required_tools"]) <= known, path.name)
            if "playbook" in expect:
                self.assertIn(expect["playbook"], prod.PLAYBOOKS)
                self.assertTrue((ROOT / f"docs/playbooks/{expect['playbook']}.md").is_file())
                self.assertIn("get_playbook", expect["required_tools"])
            for group in expect["must_mention"]:
                self.assertTrue(group and all(isinstance(g, str) for g in group))
            for rx in expect["must_not"]:
                re.compile(rx)
            for tool in expect["required_tools"]:  # a required tool must be answerable
                self.assertTrue(tool == "get_playbook" or tool in data["tools"], (path.name, tool))


def invocation(answer, tools=(("diagnose_paid_order", None), ("get_playbook", "opencti-paid-order-stuck")), state="completed"):
    history = []
    for name, playbook in tools:
        args = {"name": playbook} if playbook else {}
        history.append({"role": "agent", "parts": [{"kind": "data", "data": {"name": name, "args": args}}]})
        history.append({"role": "agent", "parts": [{"kind": "data", "data": {"name": name, "response": {
            "content": [{"type": "text", "text": json.dumps({"name": playbook} if playbook else {"status": "observed"})}]}}}]})
    history.append({"role": "agent", "parts": [{"kind": "text", "text": answer}]})
    return {"status": {"state": state}, "history": history}


EXPECT = {"playbook": "opencti-paid-order-stuck", "required_tools": ["diagnose_paid_order", "get_playbook"],
          "must_mention": [["DeadlineExceeded"], ["image"]], "must_not": [r"delete (the )?job", r"pay (again|twice)"]}
GOOD = "The Job hit DeadlineExceeded because its image could not be pulled. Escalate. Never delete the Job or pay again."


class GraderTests(unittest.TestCase):
    def grade(self, inv, expect=EXPECT):
        return evalrun.grade(inv, expect)

    def failed(self, result):
        return sorted(k for k, v in result["checks"].items() if not v)

    def test_good_answer_passes(self):
        result = self.grade(invocation(GOOD))
        self.assertTrue(result["passed"], result)

    def test_missing_required_tool_fails(self):
        result = self.grade(invocation(GOOD, tools=(("get_playbook", "opencti-paid-order-stuck"),)))
        self.assertFalse(result["passed"])
        self.assertEqual(self.failed(result), ["tool:diagnose_paid_order"])

    def test_wrong_playbook_fails(self):
        result = self.grade(invocation(GOOD, tools=(("diagnose_paid_order", None), ("get_playbook", "opencti-l402-funnel"))))
        self.assertEqual(self.failed(result), ["playbook:opencti-paid-order-stuck"])

    def test_playbook_name_read_from_result_when_args_hidden(self):
        inv = invocation(GOOD)
        for event in inv["history"]:
            for part in event["parts"]:
                part.get("data", {}).pop("args", None)
        self.assertTrue(self.grade(inv)["passed"])

    def test_forbidden_phrase_fails(self):
        result = self.grade(invocation("DeadlineExceeded from the image. Delete the job and retry."))
        self.assertEqual(self.failed(result), ["must_not:0"])

    def test_negated_forbidden_phrase_passes(self):
        for text in ("Do not delete the job.", "You must not pay again.", "Deleting is forbidden: don't delete the Job.",
                     "**Never** delete the job or pay twice."):
            self.assertTrue(self.grade(invocation(f"DeadlineExceeded, image. {text}"))["passed"], text)

    def test_negation_does_not_leak_across_sentences(self):
        result = self.grade(invocation("DeadlineExceeded, image. Never guess. Delete the job."))
        self.assertEqual(self.failed(result), ["must_not:0"])

    def test_sentence_and_list_scoped_negations(self):
        fm = evalrun.forbidden_match
        healthy = r"\b(is|looks|appears) healthy\b"
        rows = r"\b(edit|modify|alter)\b[^.\n]{0,30}\b(rows?|database|db)\b"
        for pattern, text in (
                (healthy, "| **A** | **Verify that `order-diagnostics` is healthy**: kubectl get pods | No |"),
                (healthy, "*Confirm that the `order-diagnostics` pod is running and that the\n   Postgres instance it connects to is healthy.*"),
                (r"pay(ing)? (again|twice)", "Do not edit database rows, delete the job, or ask the customer to pay again. These are forbidden by the playbook."),
                (r"delete (the |that )?(scanner )?job", "Do not edit database rows, delete the job, or ask the customer to pay again."),
                (rows, "Do not edit database rows, delete the job, or ask the customer to pay again."),
                (r"pay(ing)? (again|twice)", "You don\u2019t need to pay again."),
                (r"pay(ing)? (again|twice)", "Ask the customer to pay again or issue a new order \u2013 prohibited."),
                (rows, "Edit database rows or delete the job/pod \u2013 this would violate the allowed actions list."),
                (rows, "What we cannot do (per the playbook and the tool constraints)\n\n- Edit database rows or delete the job/pod\n- Ask the customer to pay again"),
                (r"pay(ing)? (again|twice)", "What we cannot do (per the playbook)\n\n- Edit database rows or delete the job/pod\n- Ask the customer to pay again")):
            self.assertFalse(fm(pattern, text), text)
        for pattern, text in ((healthy, "The pricer is healthy."), (healthy, "Postgres looks healthy."),
                              ("restart", "Restart or redeploy `payment-aperture-services` to clear the crash-loop."),
                              (r"\brestart\b", "- Never restart the pricer\n- Restart payment-aperture-services"),
                              (r"pay(ing)? (again|twice)", "Ask the customer to pay again.")):
            self.assertTrue(fm(pattern, text), text)

    def test_missing_mention_fails_and_any_of_group_matches_case_insensitively(self):
        self.assertEqual(self.failed(self.grade(invocation("DeadlineExceeded only."))), ["mention:1"])
        expect = dict(EXPECT, must_mention=[["pricer", "payment-aperture-services"]], must_not=[])
        self.assertTrue(self.grade(invocation("The PRICER is down."), expect)["passed"])

    def test_non_completed_task_and_empty_answer_fail(self):
        self.assertIn("completed", self.failed(self.grade(invocation(GOOD, state="failed"))))
        self.assertFalse(self.grade({"status": {"state": "completed"}, "history": []})["passed"])

    def test_final_answer_prefers_artifacts(self):
        inv = invocation("draft")
        inv["artifacts"] = [{"parts": [{"kind": "text", "text": GOOD}]}]
        self.assertTrue(self.grade(inv)["passed"])

    def test_shipped_scenarios_grade_their_own_reference_answers(self):
        good = {"tabletop1-image-gc": "DeadlineExceeded: the image could not be pulled. Escalate for a re-scan. Never delete the Job.",
                "tabletop2-dead-pricer": "payment-aperture-services is crash looping. Do not restart Aperture or block anyone.",
                "tabletop3-rejection-spike": "Healthy, but a security signal: hypotheses are a retry loop or a reset. Do not block sources.",
                "healthy-baseline": "The payment gate is healthy; no restart is needed.",
                "diagnosis-unavailable": "The order status is unknown: the diagnostic is unavailable."}
        for path in SCENARIOS.glob("*.json"):
            expect = json.loads(path.read_text())["expect"]
            tools = [(t, expect.get("playbook") if t == "get_playbook" else None) for t in expect["required_tools"]]
            self.assertTrue(evalrun.grade(invocation(good[path.stem], tools=tools), expect)["passed"], path.stem)
            self.assertFalse(evalrun.grade(invocation("Nothing to say.", tools=tools), expect)["passed"], path.stem)

    def test_scenario_name_validation_rejects_shell_metacharacters(self):
        for bad in ("a;b", "A", "", "x" * 65, "a b", "$(id)"):
            with self.assertRaises(ValueError):
                evalrun.check_name(bad)
        self.assertEqual(evalrun.check_name("tabletop1-image-gc"), "tabletop1-image-gc")

FUNNEL = {"playbook": "opencti-l402-funnel", "required_tools": ["get_playbook"], "must_mention": [], "must_not": []}
FUNNEL_TOOLS = (("get_playbook", "opencti-l402-funnel"),)
LIVE = ("The pricer is down: check payment-pricer-service. Customers can pay by card or PayPal instead. "
        "Escalate if it stays down > 30 min.")


class InventionTests(unittest.TestCase):
    def grade(self, answer, expect=FUNNEL, question=""):
        return evalrun.grade(invocation(answer, tools=FUNNEL_TOOLS), expect, question)

    def failed(self, result):
        return sorted(k for k, v in result["checks"].items() if not v)

    def test_known_names(self):
        for name in ("payment-aperture-services", "l402-aperture", "lnd-merchant", "opencti-paid-scan-e2e",
                     "paid-scan-diagnosis", "opencti-l402-funnel", "paid-scan-diagnostics"):
            self.assertIn(name, evalrun.KNOWN_NAMES)
        self.assertNotIn("payment-pricer-service", evalrun.KNOWN_NAMES)

    def test_live_answer_fails_all_three_checks(self):
        result = self.grade(LIVE)
        self.assertEqual(result["unknown_components"], ["payment-pricer-service"])
        self.assertEqual(result["invented_thresholds"], ["30 minute"])
        self.assertEqual(self.failed(result), ["invented_option:0", "invented_option:1", "invented_thresholds", "unknown_components"])

    def test_dead_pricer_scenario_catches_the_three_phrases(self):
        expect = json.loads((SCENARIOS / "tabletop2-dead-pricer.json").read_text())["expect"]
        for phrase in ("payment-pricer-service is down", "card or PayPal", "wait > 30 min"):
            failed = [c for c, ok in evalrun.grade(invocation(phrase), expect)["checks"].items() if c.startswith("must_not") and not ok]
            self.assertTrue(failed, phrase)

    def test_clean_answer_passes(self):
        answer = "payment-aperture-services is crash-looping in opencti-paid-scan-e2e. This is read-only; re-check in 15 minutes."
        self.assertTrue(self.grade(answer)["passed"])  # 15 minutes is in the playbook

    def test_negated_invented_option_passes(self):
        self.assertTrue(self.grade("There is no PayPal option; x402 is the only rail.")["passed"])
        self.assertFalse(self.grade("Offer Stripe as a fallback.")["passed"])

    def test_common_terms_do_not_trigger(self):
        self.assertEqual(self.grade("A read-only, low-severity follow-up: re-run the end-to-end check.")["unknown_components"], [])

    def test_threshold_from_tool_results_or_question_is_allowed(self):
        self.assertEqual(self.grade("Wait 7 minutes.")["invented_thresholds"], ["7 minute"])
        self.assertEqual(self.grade("Wait 7 minutes.", question="Since 7 min ago, diagnose.")["invented_thresholds"], [])
        inv = invocation("The window is 45 minutes.", tools=FUNNEL_TOOLS)
        inv["history"][1]["parts"][0]["data"]["response"]["content"][0]["text"] = json.dumps({"content": "window 45m"})
        self.assertEqual(evalrun.grade(inv, FUNNEL)["invented_thresholds"], [])

    def test_units_are_families(self):
        self.assertEqual(self.grade("Give it 15 hours.")["invented_thresholds"], ["15 hour"])
        self.assertEqual(self.grade("Give it 24-hour baseline, 15m window.")["invented_thresholds"], [])


class LabeledGraderTests(unittest.TestCase):
    def test_grader_matches_labeled_snippets(self):
        labels = json.loads((ROOT / "tests/eval/grader_labels.json").read_text())
        expect = dict(FUNNEL, must_not=json.loads((SCENARIOS / "healthy-baseline.json").read_text())["expect"]["must_not"])
        tp = fp = fn = tn = 0
        wrong = []
        for label in labels:
            flagged = not evalrun.grade(invocation(label["text"], tools=FUNNEL_TOOLS), expect)["passed"]
            tp, fp, fn, tn = tp + (flagged and label["invention"]), fp + (flagged and not label["invention"]), \
                fn + (not flagged and label["invention"]), tn + (not flagged and not label["invention"])
            if flagged != label["invention"]:
                wrong.append(label["text"])
        message = (f"TP={tp} FP={fp} FN={fn} TN={tn} precision={tp / max(tp + fp, 1):.2f} "
                   f"recall={tp / max(tp + fn, 1):.2f}; misclassified: {wrong}")
        print(message)
        self.assertGreaterEqual(tp, 4)
        self.assertGreaterEqual(tn, 5)
        self.assertEqual(wrong, [], message)


class NormalizeTests(unittest.TestCase):
    def test_unicode_dashes_and_ranges(self):
        self.assertEqual(evalrun.normalize("a\u2011b\u2010c\u2212d"), "a-b-c-d")
        self.assertEqual(evalrun.normalize("5\u201310 minutes, up \u2014 now"), "5-10 minutes, up - now")
        self.assertEqual(evalrun.thresholds("Re-run in 5-10 minutes"), {(5, "minute"), (10, "minute")})

    def test_regrade_reads_saved_runs_without_modifying_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "paid-scan-eval-1-diagnosis-unavailable-run1.json")
            text = json.dumps({"scenario": "diagnosis-unavailable", "run": 1, "passed": False, "checks": {}, "invocation":
                               invocation("The status is unknown and the diagnostic is unavailable.", tools=(("diagnose_paid_order", None),))})
            path.write_text(text)
            with unittest.mock.patch("sys.stdout"):
                self.assertEqual(evalrun.main(["--regrade", tmp]), 0)
            self.assertEqual(path.read_text(), text)
            self.assertEqual(len(list(pathlib.Path(tmp).glob("*-regrade-summary.json"))), 1)


class DeployAgentTests(unittest.TestCase):
    def test_deploy_ships_fixture_source_and_scenarios(self):
        text = (ROOT / "ops/deploy-agent").read_text()
        self.assertIn("agent/paid_scan_eval_fixture.py", text)
        self.assertIn("paid-scan-eval-scenarios", text)
        self.assertIn('tests/eval/scenarios', text)
        self.assertRegex(text, r"sorted\(.*glob\(\"\*\.json\"\)")


def helm(*sets):
    cmd = ["helm", "template", "r", str(ROOT / "charts/agent"), "--namespace", "lndops-agent",
           "--set", "paidScan.enabled=true", "--set", "paidScan.origin=https://diagnostics.example:8443"]
    for s in sets:
        cmd += ["--set", s]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def docs(rendered):
    out = {}
    for doc in re.split(r"^---\n", rendered, flags=re.M):
        kind = re.search(r"^kind: (\S+)", doc, re.M)
        name = re.search(r"^  name: (\S+)", doc, re.M) or re.search(r"^metadata: \{name: ([^,}]+)", doc, re.M)
        if kind and name:
            out[(kind.group(1), name.group(1))] = doc
    return out


def system_message(doc):
    return re.search(r"systemMessage: \|\n(.*?)\n    tools:", doc, re.S).group(1)


@unittest.skipUnless(shutil.which("helm"), "helm not installed")
class ChartTests(unittest.TestCase):
    def test_eval_is_off_by_default(self):
        rendered = helm()
        self.assertNotIn("paid-scan-eval", rendered)
        self.assertIn(("Agent", "paid-scan-diagnosis"), docs(rendered))

    def test_eval_objects_render_when_enabled(self):
        found = docs(helm("paidScan.eval.enabled=true"))
        for key in (("Deployment", "paid-scan-eval-fixture"), ("Service", "paid-scan-eval-fixture"),
                    ("NetworkPolicy", "paid-scan-eval-fixture"), ("NetworkPolicy", "kagent-paid-scan-eval"),
                    ("RemoteMCPServer", "paid-scan-eval"), ("Agent", "paid-scan-diagnosis-eval")):
            self.assertIn(key, found)
        deployment = found[("Deployment", "paid-scan-eval-fixture")]
        self.assertIn("automountServiceAccountToken: false", deployment)
        self.assertNotIn("secret", deployment.lower())
        self.assertIn("paid_scan_eval_fixture.py", deployment)
        for volume in ("runbook-gateway-source", "paid-scan-playbooks", "paid-scan-eval-scenarios", "emptyDir"):
            self.assertIn(volume, deployment)
        policy = found[("NetworkPolicy", "paid-scan-eval-fixture")]
        self.assertIn("lndops-kagent", policy)
        self.assertNotIn("ipBlock", policy)
        self.assertNotIn("lndops-monitoring", policy)

    def test_both_agents_share_message_and_tools(self):
        found = docs(helm("paidScan.eval.enabled=true"))
        prod, ev = found[("Agent", "paid-scan-diagnosis")], found[("Agent", "paid-scan-diagnosis-eval")]
        self.assertEqual(system_message(prod), system_message(ev))
        for phrase in ("call get_playbook", "you cannot change anything", "Ask for the IDs only when", "If get_playbook returns unknown"):
            self.assertIn(phrase, system_message(ev))
        tools = lambda doc: re.search(r"toolNames: (\[.*?\])", doc).group(1)
        self.assertEqual(tools(prod), tools(ev))
        self.assertIn("name: paid-scan-eval\n", ev)
        self.assertIn("modelConfig: default-model-config", ev)


if __name__ == "__main__":
    unittest.main()
