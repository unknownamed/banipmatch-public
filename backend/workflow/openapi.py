"""Document the actual additional boundaries rather than generic dict bodies."""
from copy import deepcopy

from .security import LIMITS


def augment(spec):
    schemas = spec["components"]["schemas"]
    schemas["SessionSnapshot"] = {"allOf": [
        {"$ref": "#/components/schemas/Snapshot"},
        {"type": "object", "properties": {"data_mode": {"const": "simulated"},
            **{key: {"type":"array", "maxItems": limit} for key,limit in LIMITS.items()}}}],
        "description": "모의/가정 근거만 허용. 등록과 계산 가능 검사는 별개. v0.1 의미검사·보호 조건 유지."}
    schemas["SessionRunRequest"] = {"allOf": [{"$ref":"#/components/schemas/RunRequest"},
        {"type":"object","properties":{"time_limit_seconds":{"maximum":10},"seed":{"minimum":0,"maximum":2**31-1}}}]}
    schemas["Revision"]["properties"]["snapshot"] = {"$ref":"#/components/schemas/SessionSnapshot"}
    schemas["PushSubscription"] = {"type":"object","additionalProperties":False,
        "required":["endpoint","keys"], "properties":{
            "endpoint":{"type":"string","format":"uri","maxLength":2048,"description":"허용한 HTTPS 푸시 중계망만. 전송 때 DNS 공인주소 검사·IP pinning, redirect 금지."},
            "keys":{"type":"object","additionalProperties":False,"required":["p256dh","auth"],
                    "properties":{"p256dh":{"type":"string","description":"URL-safe base64 P-256 공개키"},
                                  "auth":{"type":"string","description":"URL-safe base64 16byte 인증 비밀"}}},
            "expirationTime":{"type":["integer","null"]}}}
    schemas["Subscription"]["properties"]["subscription"] = {"$ref":"#/components/schemas/PushSubscription"}
    mappings = [
        ("/v2/examples/default","get","Snapshot","200"),
        ("/v2/scenarios","post","RegisteredScenario","201"),
        ("/v2/scenarios/{scenario_id}","get","Snapshot","200"),
        ("/v2/runs","post","Run","202"),
        ("/v2/runs/{run_id}","get","Run","200"),
        ("/v2/runs/{run_id}/results","get","Results","200"),
        ("/v2/plans/{plan_id}","get","Plan","200"),
        ("/v2/plans/{plan_id}/next-input","get","Snapshot","200"),
        ("/v2/plans/{plan_id}/approvals","post","Approval","201"),
    ]
    for path,method,name,status in mappings:
        operation = spec["paths"][path][method]
        operation["responses"].pop("200",None)
        operation["responses"][status] = {"description":"Success","content":{"application/json":{"schema":{"$ref":"#/components/schemas/"+name}}}}
    for path,name in (("/v2/scenarios","SessionSnapshot"),("/v2/runs","SessionRunRequest"),
                      ("/v2/plans/{plan_id}/approvals","ApprovalRequest")):
        spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"] = {"$ref":"#/components/schemas/"+name}
    result = spec["paths"]["/v2/runs/{run_id}/results"]["get"]
    result["responses"]["202"] = {"description":"queued/running","content":{"application/json":{"schema":{"$ref":"#/components/schemas/Run"}}}}
    spec["components"].setdefault("responses", {})["WorkflowError"] = {
        "description":"ApiError code로 구분", "content":{"application/json":{"schema":{"$ref":"#/components/schemas/Error"}}}}
    parameters = spec["components"].setdefault("parameters", {})
    for name, key, schema in (("WorkflowOrigin","Origin",{"type":"string"}),
                              ("WorkflowKey","Idempotency-Key",{"type":"string","minLength":1,"maxLength":128}),
                              ("WorkflowCsrf","X-CSRF-Token",{"type":"string"})):
        parameters[name] = {"name":key,"in":"header","required":True,"schema":schema}
    for path,operations in spec["paths"].items():
        if not path.startswith("/v2/"):
            continue
        for method,operation in operations.items():
            if method in {"post","delete"}:
                headers = [{"$ref":"#/components/parameters/WorkflowOrigin"}]
                if path != "/v2/session" or method != "post":
                    headers.append({"$ref":"#/components/parameters/WorkflowKey"})
                    if not (method == "post" and path == "/v2/recipient/session"):
                        headers.append({"$ref":"#/components/parameters/WorkflowCsrf"})
                operation.setdefault("parameters",[]).extend(headers)
            for status in ("400","401","403","404","409","410","413","415","422","429","503"):
                operation["responses"][status] = {"$ref":"#/components/responses/WorkflowError"}
    for path in ("/v2/recipient/session","/v2/plans/{plan_id}/dispatches"):
        op = spec["paths"][path]["post"]
        op["responses"]["200"] = deepcopy(op["responses"]["201" if path.endswith("session") else "202"])
    return spec


def export(spec):
    value = deepcopy(spec)
    value["paths"] = {p:v for p,v in value["paths"].items() if p.startswith("/v2/")}
    value.pop("security",None)
    value["components"]["securitySchemes"] = {k:v for k,v in value["components"]["securitySchemes"].items()
                                               if k in {"DispatcherCookie","RecipientCookie"}}
    return value
