"""Static checks of the Step Functions definition and the SAM template (no AWS calls)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_INFRA = Path(__file__).resolve().parents[2] / "infra"
_ASL = _INFRA / "statemachine" / "rebellion.asl.json"
_TEMPLATE = _INFRA / "template.yaml"


@pytest.fixture(scope="module")
def asl() -> dict:
    return json.loads(_ASL.read_text(encoding="utf-8"))


def test_state_machine_flow(asl):
    states = asl["States"]
    assert asl["StartAt"] == "Preflight"
    assert states["Preflight"]["Next"] == "Fetch"
    assert states["Fetch"]["Next"] == "ExtractEach"
    assert states["ExtractEach"]["Type"] == "Map"
    assert states["ExtractEach"]["Next"] == "Assemble"
    assert states["Assemble"]["Next"] == "AcceptedChoice"
    assert "PublishedChoice" not in states
    for name in ("Preflight", "Fetch", "Assemble"):
        assert states[name]["Type"] == "Task"


def test_fetch_receives_the_execution_name(asl):
    payload = asl["States"]["Fetch"]["Parameters"]["Payload"]
    assert payload["execution.$"] == "$$.Execution.Name"


def test_map_runs_inline_with_bounded_concurrency(asl):
    mapping = asl["States"]["ExtractEach"]
    assert mapping["MaxConcurrency"] == 5
    assert mapping["ItemsPath"] == "$.staged.items"
    assert mapping["ResultPath"] == "$.results"
    assert mapping["ItemProcessor"]["ProcessorConfig"]["Mode"] == "INLINE"
    assert set(mapping["ItemSelector"]) == {"key.$", "model_id.$", "report_date.$"}


def test_extract_retries_twice_with_backoff(asl):
    inner = asl["States"]["ExtractEach"]["ItemProcessor"]
    extract = inner["States"][inner["StartAt"]]
    assert extract["Type"] == "Task"
    [retry] = extract["Retry"]
    assert retry["ErrorEquals"] == ["States.ALL"]
    assert retry["MaxAttempts"] == 2
    assert retry["IntervalSeconds"] == 10
    assert retry["BackoffRate"] == 2


def test_extract_catch_discards_the_article(asl):
    inner = asl["States"]["ExtractEach"]["ItemProcessor"]
    extract = inner["States"][inner["StartAt"]]
    [catch] = extract["Catch"]
    assert catch["ErrorEquals"] == ["States.ALL"]
    discard = inner["States"][catch["Next"]]
    assert discard["Type"] == "Pass"
    assert discard["Parameters"]["status"] == "discarded"
    assert discard["Parameters"]["key.$"] == "$.key"
    # Only the error name travels with the item (never the multi-KB Cause / stack trace),
    # so a mass-failure run stays under the 256 KB payload limit and reaches Assemble.
    assert discard["Parameters"]["error.$"] == "$.error.Error"
    assert discard["End"] is True


def test_rejected_batch_fails_the_execution_after_publishing(asl):
    states = asl["States"]
    choice = states["AcceptedChoice"]
    assert choice["Type"] == "Choice"
    [rule] = choice["Choices"]
    assert rule["Variable"] == "$.accepted"
    assert rule["BooleanEquals"] is False
    assert rule["Next"] == "BatchRejectedFail"
    fail = states["BatchRejectedFail"]
    assert fail["Type"] == "Fail"
    assert fail["Error"] == "BatchRejected"
    assert "still published" in fail["Cause"]
    assert states[choice["Default"]]["Type"] == "Succeed"
    assert "ReportAborted" not in _ASL.read_text(encoding="utf-8")


def test_function_arns_are_substituted(asl):
    text = _ASL.read_text(encoding="utf-8")
    for name in ("Preflight", "Fetch", "Extract", "Assemble"):
        assert "${" + name + "FunctionArn}" in text


# ---- SAM template ----------------------------------------------------------


def _load_template() -> dict:
    yaml = pytest.importorskip("yaml")

    class CfnLoader(yaml.SafeLoader):
        pass

    def _tag(loader, suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return {suffix: loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {suffix: loader.construct_sequence(node, deep=True)}
        return {suffix: loader.construct_mapping(node, deep=True)}

    CfnLoader.add_multi_constructor("!", _tag)
    return yaml.load(_TEMPLATE.read_text(encoding="utf-8"), Loader=CfnLoader)  # noqa: S506


def test_template_has_no_optional_agent_or_sqs():
    text = _TEMPLATE.read_text(encoding="utf-8")
    for banned in ("UseAgent", "EnableAgent", "USE_AGENT", "SQS"):
        assert banned not in text


def test_template_parameters():
    params = _load_template()["Parameters"]
    assert params["PerFeedLimit"]["Default"] == "25"
    assert params["AgentModelId"]["Default"] == "global.anthropic.claude-sonnet-4-6"
    assert "AgentRegion" in params


def test_template_state_machine_owns_the_schedule():
    resources = _load_template()["Resources"]
    machine = resources["RebellionStateMachine"]
    assert machine["Type"] == "AWS::Serverless::StateMachine"
    props = machine["Properties"]
    assert props["DefinitionUri"] == "statemachine/rebellion.asl.json"
    assert set(props["DefinitionSubstitutions"]) == {
        "PreflightFunctionArn",
        "FetchFunctionArn",
        "ExtractFunctionArn",
        "AssembleFunctionArn",
    }
    [event] = props["Events"].values()
    assert event["Type"] == "Schedule"
    for name, res in resources.items():
        if res["Type"] == "AWS::Serverless::Function":
            assert "Events" not in res["Properties"], name


def test_template_stage_functions_and_bedrock_scope():
    resources = _load_template()["Resources"]
    handlers = {
        name: res["Properties"]["Handler"]
        for name, res in resources.items()
        if res["Type"] == "AWS::Serverless::Function"
    }
    assert handlers == {
        "PreflightFunction": "pipeline.stages.preflight",
        "FetchFunction": "pipeline.stages.fetch",
        "ExtractFunction": "pipeline.stages.extract",
        "AssembleFunction": "pipeline.stages.assemble",
    }
    assert 120 <= resources["ExtractFunction"]["Properties"]["Timeout"] <= 300

    def bedrock_actions(name: str) -> set[str]:
        text = json.dumps(resources[name]["Properties"].get("Policies", []))
        return set(re.findall(r'"(bedrock:[A-Za-z]+)"', text))

    invoke = {
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream",
    }
    # Least privilege: Preflight only reads model metadata, Extract only invokes.
    assert bedrock_actions("PreflightFunction") == {
        "bedrock:GetInferenceProfile",
        "bedrock:GetFoundationModel",
    }
    assert bedrock_actions("ExtractFunction") == invoke
    assert bedrock_actions("FetchFunction") == set()
    assert bedrock_actions("AssembleFunction") == set()


def test_template_expires_staging_objects():
    bucket = _load_template()["Resources"]["SnapshotBucket"]["Properties"]
    [rule] = bucket["LifecycleConfiguration"]["Rules"]
    assert rule["Prefix"] == "staging/"
    assert rule["ExpirationInDays"] == 7
    assert rule["Status"] == "Enabled"


@pytest.mark.parametrize("function", ["FetchFunction", "AssembleFunction"])
def test_template_lets_fetch_and_assemble_read_the_latest_report(function):
    resources = _load_template()["Resources"]
    statements = [
        stmt
        for policy in resources[function]["Properties"]["Policies"]
        if isinstance(policy, dict) and "Statement" in policy
        for stmt in policy["Statement"]
    ]
    assert {
        "Effect": "Allow",
        "Action": "s3:GetObject",
        "Resource": {"Sub": "${SnapshotBucket.Arn}/snapshots/latest/*"},
    } in statements
    # Without ListBucket, S3 answers AccessDenied instead of NoSuchKey on the first run.
    # The grant must be unconditioned: the implicit ListBucket check behind a GetObject
    # carries no s3:prefix, so a prefix condition would never apply.
    listing = [stmt for stmt in statements if stmt.get("Action") == "s3:ListBucket"]
    assert listing == [
        {
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": {"GetAtt": "SnapshotBucket.Arn"},
        }
    ]


def test_template_description_mentions_the_rolling_window():
    description = " ".join(_load_template()["Description"].split())
    assert "rolling 30-day window" in description
    assert "aborts" not in description


def test_template_functions_are_packaged_from_the_build_folder():
    template = _load_template()
    resources = template["Resources"]
    functions = {
        name: res for name, res in resources.items() if res["Type"] == "AWS::Serverless::Function"
    }
    assert len(functions) == 4
    # The SAM builder must match the Lambda runtime, or dependencies are built for the wrong one.
    assert template["Globals"]["Function"]["Runtime"] == "python3.13"
    for name, res in functions.items():
        assert res["Properties"]["CodeUri"] == ".build/lambda", name
        assert res["Metadata"]["BuildMethod"] == "python3.13", name
    assert (_INFRA / "build-lambda.sh").is_file()


def test_cloudfront_reads_only_the_site_and_the_snapshots():
    policy = _load_template()["Resources"]["SnapshotBucketPolicy"]["Properties"]
    [statement] = policy["PolicyDocument"]["Statement"]
    assert statement["Principal"] == {"Service": "cloudfront.amazonaws.com"}
    assert statement["Action"] == "s3:GetObject"
    resources = [r["Sub"] for r in statement["Resource"]]
    assert resources == [
        "${SnapshotBucket.Arn}/index.html",
        "${SnapshotBucket.Arn}/assets/*",
        "${SnapshotBucket.Arn}/geo/*",
        "${SnapshotBucket.Arn}/snapshots/*",
    ]
    assert "${SnapshotBucket.Arn}/*" not in resources
    assert not any("staging" in r for r in resources)
