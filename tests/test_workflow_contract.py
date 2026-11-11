import json

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

from backend.api.app import create_app
from backend.api.contracts import ROOT
from backend.api.settings import Settings
from backend.workflow.openapi import export


def test_published_v02_contract_matches_runtime_and_all_examples_validate():
    directory = ROOT / "docs" / "development" / "v0.2"
    published = json.loads((directory / "openapi.json").read_text(encoding="utf-8"))
    actual = export(create_app(Settings(workflow_enabled=True, run_mode="engine")).openapi())
    assert actual == published
    validate(published)
    assert published["info"]["version"] == "0.2.0"
    assert all(path.startswith("/v2/") for path in published["paths"])
    examples = json.loads((directory / "examples.json").read_text(encoding="utf-8"))["examples"]
    for example in examples:
        schema = {"$ref":"#/components/schemas/"+example["model"], "components":published["components"]}
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(example["value"])


def test_new_cookie_and_error_contracts_do_not_inherit_legacy_bearer_auth():
    spec = create_app(Settings(workflow_enabled=True,run_mode="engine")).openapi()
    assert spec["paths"]["/v2/session"]["post"]["security"] == []
    assert spec["paths"]["/v2/recipient/session"]["post"]["security"] == []
    assert spec["paths"]["/v2/recipient/notifications"]["get"]["security"] == [{"RecipientCookie":[]}]
    assert spec["paths"]["/v2/recipients"]["get"]["security"] == [{"DispatcherCookie":[]}]
    assert spec["paths"]["/v2/runs"]["post"]["responses"]["422"] == {"$ref":"#/components/responses/WorkflowError"}
