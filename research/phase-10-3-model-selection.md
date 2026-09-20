---
Number:        — (unnumbered; promote to docs/ as the next free number)
Title:         Phase 10.3 — Model Selection as a User Surface
Type:          RESEARCH
Status:        ACCEPTED (frozen)
Created:       2026-09-20
Supersedes:    —
Superseded-by: —
Depends-on:    0002, 0013, 0021, 0033, 0034, 0037
---

# Phase 10.3 — Model Selection as a User Surface

Frozen research deliverable for `docs/0037` Part B, Phase 10.3.

**Environment under test.** `litellm==1.100.0` (the pin in `pyproject.toml`,
`proxy = ["litellm[proxy]>=1.100.0"]`; installed at
`C:\Users\csdee\openhands\.venv\Lib\site-packages\litellm`), `openai==2.54.0`,
`openhands-sdk==1.45.0`, Python 3.13, Windows 11. Code claims cite
`path::symbol` against that installed tree and permalink to
`github.com/BerriAI/litellm/blob/v1.100.0/...`, which was confirmed to resolve
(2026-09-20).

**Method note.** Claims marked *(measured)* were produced by running a real
LiteLLM 1.100.0 proxy on localhost against three fake deployments whose
`model_info.id` values mirror `agentctl proxy`'s scheme
(`openrouter-a1-m0`, `gemini-a1-m0`, `anthropic-a1-m0`) and whose `api_base`
pointed at `http://127.0.0.1:9/v1` (a guaranteed connection refusal). **No
provider key was used and no free-tier quota was consumed.** Transcripts of
those runs are reproduced inline.

---

## 1. Executive answer

**LiteLLM already normalises cross-provider tool-call history, and it does so
more completely than the owner would plausibly build — the correct answer to
Part 1 is CONFIGURE, not BUILD.** Version 1.100.0 rewrites tool definitions,
tool-call emission, tool-result return, parallel-call grouping and system-prompt
placement for Anthropic and Gemini, and it already contains dedicated,
commented machinery for the two hazards that actually bite: it strips Gemini
thought signatures out of `tool_call_id` when the next hop is not Gemini
(`utils.py::function_setup`), and it drops Anthropic thinking blocks whose
signature cannot be verified (`factory.py::_drop_unsignable_thinking_blocks`).
The one thing the owner must change is a config flag: `modify_params: true`,
without which the repair pass that fixes orphaned and duplicated tool results
returns the message list untouched.

**Part 2 splits.** The live pool *is* readable — but not from the endpoint the
brief names. `/v1/models` returns **model groups, not deployments**: against a
42-deployment pool it returns exactly two rows, `pool` and `paid` *(measured)*.
`/model/info` is the real answer: one row per deployment, `model_info.id`
preserved verbatim, `api_key` stripped, no credential required because the
generated config sets no `master_key` *(measured)*. But **cooldown state is not
on any endpoint**: it lives in the router's in-process `DualCache` and is read
only by router-internal functions. The nearest readable proxy for it,
`litellm_deployment_state` on `/metrics`, was measured still reporting
`2.0` (complete outage) **15 seconds after the cooldown had expired**, because
it is only cleared by a *subsequent successful request*. So a green Panel 1
light built on any of this would be a guess dressed as a fact, and the standing
rule forbids it.

**Part 3 is mostly nothing.** Exactly one provider in the registry exposes a
usable free-tier quota number to an ordinary inference key: OpenRouter's
`GET /api/v1/key`, whose `free_model_daily_requests` object gives `used`,
`limit` and `remaining` — and `agentctl` already calls the sibling endpoint
`/api/v1/auth/key` in `probe.py`. **Google AI Studio, Mistral and Cerebras
expose nothing usable**: Gemini documents no rate-limit headers and no quota
endpoint; Mistral's usage API needs an Admin key from the Backoffice; Cerebras'
official rate-limit page documents no headers at all. Anthropic and OpenAI have
rich per-response headers but both are paid, and Anthropic's Rate Limits API
returns *configured* limits, needs an Admin key, and is explicitly "unavailable
for individual accounts".

---

## 2. VERIFIED

### 2.1 What LiteLLM 1.100.0 already normalises (Part 1)

**V1. The OpenAI Chat Completions shape is the interchange format, and it is
what `agentctl` already speaks.** The proxy accepts `/v1/chat/completions`;
every provider config translates *from* that shape. The relevant TypedDicts are
in `litellm/types/llms/openai.py`:

| Concept | Symbol | Shape |
|---|---|---|
| tool definition | `ChatCompletionToolParam` / `OpenAIChatCompletionToolParam` | `{"type": "function", "function": {"name", "description", "parameters", "strict"}}` |
| assistant tool call | `ChatCompletionAssistantToolCall` | `{"id", "type": "function", "function": {"name", "arguments"}}` — `arguments` is a **JSON string** |
| tool result | `ChatCompletionToolMessage` | `{"role": "tool", "content", "tool_call_id"}` |
| reasoning | `ChatCompletionThinkingBlock` | `{"type": "thinking", "thinking", "signature"}` |
| system prompt | `ChatCompletionSystemMessage` | an ordinary message with `role: "system"` in the `messages` array |

[types/llms/openai.py](https://github.com/BerriAI/litellm/blob/v1.100.0/litellm/types/llms/openai.py)

**V2. Anthropic translation is implemented and structural, not cosmetic.**
`litellm/litellm_core_utils/prompt_templates/factory.py`:

- `factory.py::convert_to_anthropic_tool_invoke` turns one OpenAI `tool_calls`
  array into a list of `{"type": "tool_use", "id", "name", "input"}` content
  blocks. It calls `json.loads` on `function.arguments` (via
  `parse_tool_call_arguments`) because Anthropic's `input` is an **object**
  where OpenAI's `arguments` is a **string**.
- `factory.py::convert_to_anthropic_tool_result` turns `{"role": "tool", ...}`
  into `{"type": "tool_result", "tool_use_id", "content"}` — and critically
  changes the **role from `tool` to `user`**, because Anthropic has no `tool`
  role.
- `factory.py::_sanitize_anthropic_tool_use_id` rewrites the id to match
  Anthropic's `^[a-zA-Z0-9_-]+$` constraint, replacing every other character
  with `_`.
- `factory.py::anthropic_messages_pt` merges consecutive `user`/`tool`/
  `function` messages into a single Anthropic `user` message whose `content` is
  a list of `tool_result` blocks. Its docstring states the constraints it is
  enforcing: *"Anthropic supports roles like 'user' and 'assistant' (system
  prompt sent separately)"*, *"Each message must alternate"*.
- `llms/anthropic/chat/transformation.py::AnthropicConfig.translate_system_message`
  lifts `role: "system"` messages out of `messages` into the top-level `system`
  parameter.

[factory.py](https://github.com/BerriAI/litellm/blob/v1.100.0/litellm/litellm_core_utils/prompt_templates/factory.py) ·
[anthropic/chat/transformation.py](https://github.com/BerriAI/litellm/blob/v1.100.0/litellm/llms/anthropic/chat/transformation.py)

**V3. Gemini translation is implemented, including the camelCase / enum
mismatch.** `litellm/types/llms/vertex_ai.py` defines the target shape:

```python
class ContentType(TypedDict, total=False):
    role: Literal["user", "model"]        # NOT "assistant"
    parts: Required[list[PartType]]

class PartType(TypedDict, total=False):
    text: str
    function_call: FunctionCall           # -> functionCall
    function_response: FunctionResponse   # -> functionResponse
    thought: bool
    thoughtSignature: str

class FunctionCall(TypedDict, total=False):
    id: str        # "Supported on Gemini 3+; older Gemini models omit/reject"
    name: Required[str]
    args: dict | None

class Tools(TypedDict, total=False):
    function_declarations: list[FunctionDeclaration]

class SystemInstructions(TypedDict):
    parts: Required[list[PartType]]

class Schema(TypedDict, total=False):
    type: Literal["STRING", "INTEGER", "BOOLEAN", "NUMBER", "ARRAY", "OBJECT"]
```

Note `Schema.type` is an **uppercase enum**, not JSON Schema's lowercase
`"string"`. The conversion of the tool result is
`factory.py::convert_to_gemini_tool_call_result` (the block ending
`_part: Final[VertexPartType] = {"function_response": _function_response}`),
and the system prompt is lifted by
`llms/vertex_ai/gemini/transformation.py::_transform_system_message`, which
pops every `role: "system"` message out of the list and returns a
`SystemInstructions`.

[types/llms/vertex_ai.py](https://github.com/BerriAI/litellm/blob/v1.100.0/litellm/types/llms/vertex_ai.py) ·
[vertex_ai/gemini/transformation.py](https://github.com/BerriAI/litellm/blob/v1.100.0/litellm/llms/vertex_ai/gemini/transformation.py)

**V4. Gemini thought signatures are smuggled through `tool_call_id`, and
LiteLLM strips them when crossing a provider boundary.** This is the single
most important normalisation for this project, and it exists already:

```python
# factory.py
THOUGHT_SIGNATURE_SEPARATOR: Final = "__thought__"

def _encode_tool_call_id_with_signature(tool_call_id, thought_signature) -> str:
    """Format: call_<uuid>__thought__<base64_signature>
    See: https://ai.google.dev/gemini-api/docs/thought-signatures"""
```

and in `utils.py::function_setup` (the body of the `client` decorator applied to
every completion), verbatim:

```
### REMOVE THOUGHT SIGNATURES FROM TOOL CALL IDS FOR NON-GEMINI MODELS ###
# Gemini models embed thought signatures in tool call IDs. When sending
# messages with tool calls to non-Gemini providers, we need to remove these
# signatures to ensure compatibility.
```

It resolves the target provider via `get_llm_provider`, and if
`_is_gemini_model(...)` is false, rewrites the history through
`utils.py::_remove_thought_signatures_from_messages`. The failure is
non-fatal — the `except` logs a warning and proceeds.

**V5. Unsignable Anthropic thinking blocks are dropped, not carried.**

```python
# factory.py::_is_unsignable_thinking_block
"""A `thinking` block that Anthropic cannot accept on input.
Anthropic verifies the thinking signature cryptographically, so a block whose
signature is null, empty, or missing (e.g. from an open-source reasoning model)
is rejected with a 400 and must be dropped rather than blanked or repaired.
`redacted_thinking` blocks carry no signature and are always kept."""
```

with `factory.py::_drop_unsignable_thinking_blocks` doing the filtering. This is
exactly the "reasoning block from provider A is unsafe on provider B" hazard,
already handled.

**V6. The tool-history repair pass exists but is OFF in `agentctl`'s
generated config.** `factory.py::sanitize_messages_for_tool_calling` handles
four documented cases:

- **Case A** orphaned tool calls — an assistant `tool_calls` with no following
  result gets a synthetic result injected (`_add_missing_tool_results`).
- **Case B** orphaned tool results — a `tool` message whose `tool_call_id` has
  no matching call is dropped (`_is_orphaned_tool_result`).
- **Case C** empty text content — replaced with a placeholder.
- **Case D** duplicate results for one `tool_call_id` — deduplicated, keeping
  the last, because *"Anthropic requires exactly one tool_result per tool_use
  and rejects with: 'each tool_use must have a single result'"*.

Its first statement is:

```python
    if not litellm.modify_params:
        return messages
```

`proxy/proxy_config.yaml` sets `litellm_settings: drop_params: true` and does
**not** set `modify_params`. So Cases A, B and D are inert today.

(One sanitisation is unconditional: `anthropic_messages_pt` applies
`_sanitize_empty_text_content` regardless of `modify_params`, because an empty
text block always 400s on Anthropic.)

**V7. `drop_params: true` silently discards unsupported parameters.**
`utils.py::get_optional_params::_check_valid_arg`:

```python
if (litellm.drop_params is True or drop_params is True) and k not in supported_params:
    non_default_params.pop(k, None)
    passed_params.pop(k, None)
elif k not in supported_params:
    raise UnsupportedParamsError(...)
```

`supported_params` is resolved **per provider config, not per model** — e.g.
`llms/openai/chat/gpt_transformation.py::OpenAIGPTConfig.get_supported_openai_params`
lists `"tools"`, `"tool_choice"`, `"parallel_tool_calls"` unconditionally.

**V8. Which errors cool a deployment down — and which do not.**
`router_utils/cooldown_handlers.py::_is_cooldown_required`: for 4xx, only
**429, 401, 408 and 404** cool down; *"Do NOT cool down all other 4XX Errors"*.
All non-4xx errors do. Two consequences that matter here:

- A **400 context-window-exceeded does not cool down** the pool, and
  `litellm._should_retry(400)` is false so it is not retried across
  deployments either. It surfaces to the client as a 400.
- An **HTTP 402** (Cerebras "Payment required to access this resource",
  `docs/0034` §5) is a 4xx that is neither retried nor cooled down — which is
  precisely why `docs/0034` measured ~11% of requests failing. The source now
  confirms the mechanism behind that observation.

Cooldown threshold logic is `cooldown_handlers.py::_should_cooldown_deployment`;
because `router_settings` sets `allowed_fails: 1`, the router takes the
`should_cooldown_based_on_allowed_fails_policy` branch rather than the
error-rate branch.

### 2.2 What the running proxy actually exposes (Part 2)

All of the following were *(measured)* against litellm 1.100.0.

**V9. `/v1/models` returns model GROUPS, not deployments.** Three configured
deployments in two groups produced two rows:

```
$ curl -s http://127.0.0.1:4111/v1/models
{"data":[{"id":"pool","object":"model","created":1677610602,"owned_by":"openai"},
         {"id":"paid","object":"model","created":1677610602,"owned_by":"openai"}],
 "object":"list"}
```

Against the real 42-deployment config this returns **exactly two rows**. It
carries no account, no key, no health. Handler:
`proxy/proxy_server.py::model_list`; row builder
`proxy/utils.py::create_model_info_response`; response type
`types/proxy/model_listing.py::ModelInfoResponse`
(`id`, `object`, `created`, `owned_by`, optional `mode`,
`max_input_tokens`, `max_output_tokens`, optional `metadata.fallbacks` under
`?include_metadata=true`).

**V10. `/model/info` returns one row per deployment, with `model_info.id`
preserved and the key stripped.** Measured (abridged; the real payload carries
~150 pricing/capability fields per row):

```jsonc
{"data":[
 {"model_name":"pool",
  "litellm_params":{"api_base":"http://127.0.0.1:9/v1","model":"openai/fake-model-a"},
  "model_info":{"id":"openrouter-a1-m0","db_model":false,"free":true,
                "key":"openai/fake-model-a",
                "max_input_tokens":null,"max_output_tokens":null,
                "supports_function_calling":null,"tpm":null,"rpm":null,
                "supported_openai_params":["...","tools","tool_choice","..."]}},
 {"model_name":"pool","litellm_params":{...,"model":"openai/fake-model-b"},
  "model_info":{"id":"gemini-a1-m0","free":true,...}},
 {"model_name":"paid","litellm_params":{...,"model":"openai/fake-paid"},
  "model_info":{"id":"anthropic-a1-m0","free":false,...}}]}
```

Three facts follow, all load-bearing for the interface spec:

1. **`agentctl`'s own account labels survive.** `router.py` preserves a
   declared id (`declared_id = None if _model_info.get("id") is None else ...`;
   it only generates one when `"id" not in _model_info`). So
   `openrouter-a2-m1` comes back intact and the dashboard can parse
   `provider-aN-mI` straight back to an **account**, which is the unit
   `docs/0033` says matters.
2. **No credential leaks.** `proxy/common_utils/openai_endpoint_utils.py::remove_sensitive_info_from_deployment`
   pops `api_key`, `client_secret`, `vertex_credentials`, `aws_*`. The measured
   payload contains no `api_key`. This is compatible with the dashboard's rule
   that key values are never displayed.
3. **`model_info.free` is carried through**, so free and paid rows are
   distinguishable without re-deriving from the registry.

**V11. The proxy is unauthenticated as `agentctl` generates it.**
`agentctl/control/proxy.py::build` emits no `master_key` and no `database_url`.
`proxy/auth/user_api_key_auth.py` returns an `INTERNAL_USER` token when
`master_key is None`, and `common_checks` is skipped entirely in that case.
Measured: `/v1/models` and `/model/info` answered with no `Authorization`
header at all.

**V12. The health endpoints say nothing about deployments.** Measured:

```
$ curl -s http://127.0.0.1:4111/health/readiness
{"status":"healthy","db":"Not connected"}

$ curl -s -i http://127.0.0.1:4111/health/liveliness
HTTP/1.1 200 OK ... content-length: 12      # the string "I'm alive!"
```

`_health_endpoints.py::health_liveliness` returns the literal `"I'm alive!"`
(or `{"status":"shutting_down"}` + 503 during graceful drain).
`_health_endpoints.py::health_readiness` returns `{"status","db"}` only unless
`general_settings.allow_public_health_readiness_details` is set, which upgrades
it to `_get_health_readiness_details` (`status`, `db`, `cache`,
`litellm_version`, `success_callbacks`, `use_aiohttp_transport`, `log_level`,
`is_detailed_debug`, `show_no_redis_warning`). **None of these fields is
per-deployment.** Both answer "is the proxy process alive", not "can I work".

**V13. `/health` is the only endpoint that knows the truth, and it costs one
real completion per deployment.** Measured shape:

```jsonc
{"healthy_endpoints":[],
 "unhealthy_endpoints":[
   {"model":"openai/fake-model-a","max_tokens":16,
    "error":"litellm.InternalServerError: ... Connection error.",
    "raw_request_typed_dict":{"raw_request_api_base":"http://127.0.0.1:9/v1/",
      "raw_request_body":{"model":"fake-model-a",
        "messages":[{"role":"user","content":"Hey how's it going?"}],
        "max_tokens":16},
      "raw_request_headers":{"Authorization":"Be****-a"}},
    "model_id":"openrouter-a1-m0","exception_status":500}],
 "healthy_count":0,"unhealthy_count":1}
```

`model_id` and `exception_status` per deployment — exactly what Panel 1 wants.
But the probe is a real chat completion: `proxy/health_check.py::_get_random_llm_message`
returns one of `["Hey how's it going?", "What's 1 + 1?"]`, and
`proxy/health_check.py::filter_deployments_by_id` dedupes **by `model_info.id`**,
which is distinct for all 42 rows. **So `GET /health` against the real pool
fires 42 live completions**, i.e. it spends the very quota it is reporting on.
`docs/0034` §2 already established the rule this violates: validate for nothing.

**V14. Cooldown state is in-process only and reachable from no endpoint.** The
store is `router_utils/cooldown_cache.py::CooldownCache`, keyed
`"deployment:" + model_id + ":cooldown"` in a `DualCache`, holding
`CooldownCacheValue{exception_received, status_code, timestamp, cooldown_time}`
with the TTL set to the cooldown. Its readers are
`cooldown_handlers.py::_get_cooldown_deployments`,
`_async_get_cooldown_deployments` and
`_async_get_cooldown_deployments_with_debug_info`. A repository-wide grep for
those three symbols returns hits only in `router.py`,
`router_utils/handle_error.py` and
`router_utils/pre_call_checks/encrypted_content_affinity_check.py` — **no
route handler anywhere under `litellm/proxy/`**. There is no HTTP surface.

**V15. `healthy_only=true` does not help, and fails open by design.** Measured:
after driving three chat completions that all failed with 500 (which cooled the
pool deployments down — see V16), both of these were byte-identical to the
pre-failure response:

```
$ curl -s "http://127.0.0.1:4111/v1/models"
$ curl -s "http://127.0.0.1:4111/v1/models?healthy_only=true"
{"data":[{"id":"pool",...},{"id":"paid",...}],"object":"list"}
```

`proxy_server.py::model_list`'s own docstring says why: it *"Requires
`background_health_checks: true` in general_settings, plus either
`model_list_healthy_only` or `enable_health_check_routing` to keep deployment
health state cached; without health state the listing is returned unfiltered
(fail open)"*, and — decisively — *"nothing is hidden when `allowed_fails_policy`
is configured (cooldown remains the sole exclusion mechanism)"*. It filters on
**background-health-check** state, which is a different thing from cooldown
state and is itself paid for in live completions.

**V16. Cooldown IS observable via Prometheus — and the gauge is a lagging
indicator that will lie to you.** Measured. `/metrics` returned **404** on the
default install because `prometheus_client` is not a dependency of
`litellm[proxy]`. With `prometheus_client==0.26.0` on `PYTHONPATH` and
`litellm_settings.callbacks: ["prometheus"]`, `/metrics` mounts (307 → `/metrics/`;
`proxy_server.py` calls `PrometheusLogger._mount_metrics_endpoint()` when
`"prometheus" in callback`, with no premium gate). After four failing requests:

```
litellm_deployment_state{...,litellm_model_name="fake-model-a",model_id="openrouter-a1-m0"} 1.0
litellm_deployment_state{...,litellm_model_name="fake-model-b",model_id="gemini-a1-m0"}    1.0
litellm_deployment_state{...,litellm_model_name="pool",model_id="openrouter-a1-m0"}        2.0
litellm_deployment_state{...,litellm_model_name="pool",model_id="gemini-a1-m0"}            2.0
litellm_deployment_cooled_down_total{...,exception_status="500",model_id="openrouter-a1-m0"} 1.0
litellm_deployment_cooled_down_created{...,model_id="openrouter-a1-m0"} 1.7899108776958926e+09
```

`0 = healthy, 1 = partial outage, 2 = complete outage`
(`integrations/prometheus.py`, gauge help text). Two defects, both measured:

- **Duplicate series per deployment, with different values.** The same
  `model_id` appears twice with different `litellm_model_name` labels — `pool`
  reading 2.0 and `fake-model-a` reading 1.0. `set_deployment_partial_outage`
  is called from the failure path with the *underlying* model name, while
  `set_deployment_complete_outage` is called from
  `router_utils/cooldown_callbacks.py::router_cooldown_event_callback` with
  `_deployment["model_name"]`, i.e. the **group** name. A reader that matches
  on `model_id` alone gets two contradictory answers.
- **The gauge does not self-clear when the cooldown expires.** It is reset to 0
  only by `integrations/prometheus.py::set_deployment_healthy`, which is called
  from the *success* path. Measured directly, with `cooldown_time: 300` and no
  traffic after the failures:

```
cooldown fired at   1789910877   (cooldown_time=300 → expires 1789911177)
read at             1789911192   (15s AFTER expiry, no traffic since)
litellm_deployment_state{...,litellm_model_name="pool",model_id="openrouter-a1-m0"} 2.0
litellm_deployment_state{...,litellm_model_name="pool",model_id="gemini-a1-m0"}     2.0
```

So `2.0` means **"failed at some point and has not succeeded since"**, not "is
cooled down now". Symmetrically, `0.0` means "the last request on this
deployment succeeded", not "the next one will".

**V17. No budget or spend endpoint is usable here.** Every spend/key endpoint
in `proxy/management_endpoints/key_management_endpoints.py` guards on
`prisma_client is None` and raises `CommonProxyErrors.db_not_connected_error`
("No connected db."). `agentctl proxy` emits no `database_url`, so `/key/info`,
`/spend/logs`, `/global/spend` and friends are unavailable by construction.
The per-request headers that do exist —
`proxy/common_request_processing.py::ProxyBaseLLMRequestProcessing.get_custom_headers`
emits `x-litellm-key-max-budget`, `x-litellm-key-spend`, `x-litellm-key-tpm-limit`,
`x-litellm-key-rpm-limit` — describe the **proxy's own virtual key**, which does
not exist here. They are not provider budget.

**V18. The proxy DOES forward upstream provider rate-limit headers.** This is
the one live quota channel that survives the proxy hop.
`litellm_core_utils/llm_response_utils/get_headers.py::get_response_headers`
passes through `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`,
`x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens` verbatim, and
`_get_llm_provider_headers` re-emits **every** upstream header prefixed
`llm_provider-`. Those land in `_hidden_params["additional_headers"]` and are
spread into the client response by `get_custom_headers(**additional_headers)`
(`common_request_processing.py`). Every response also carries
**`x-litellm-model-id`**, naming the deployment that actually served it — which
for `agentctl` is the account label.

LiteLLM's own source states the limit of this channel
(`integrations/prometheus.py`, verbatim):

> *"Provider-agnostic fallback: providers like Bedrock and Vertex don't return
> `x-ratelimit-remaining-*` headers, so the gauges above only fire for OpenAI /
> Anthropic / Azure."*

### 2.3 Free-tier quota signals, per provider (Part 3)

All checked against official documentation on **2026-09-20**.

| Provider | Free tier | Response headers (official) | Endpoint (official) | Usable by a solo dev's inference key? |
|---|---|---|---|---|
| **OpenRouter** | yes | `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After` — documented **on the error response** | `GET /api/v1/key` → `limit`, `limit_remaining`, `limit_reset`, `usage`, `usage_daily`, `usage_weekly`, `usage_monthly`, `is_free_tier`, and **`free_model_daily_requests: {used, limit, remaining}`**. Bearer, normal inference key. | **YES — the only one.** |
| **Google AI Studio (Gemini)** | yes | **none documented** | **none documented**; the docs point to the AI Studio web page `aistudio.google.com/rate-limit` | **NO** |
| **Groq** | yes | `x-ratelimit-limit-requests` (RPD), `x-ratelimit-limit-tokens` (TPM), `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`, `retry-after` | none documented | **Headers only** — reactive, per response |
| **Mistral** | yes | `X-RateLimit-Remaining` referenced in the Help Center; no verbatim header table found in the API reference | `GET https://api.mistral.ai/v1/admin/usage` — requires an **Admin API key created in the Backoffice**, reports **consumed** cost/usage only, not remaining | **NO** (Admin key; consumed, not remaining) |
| **Cerebras** | contested (see `providers.py`) | **the official rate-limits page documents no headers** | none documented | **NO** (see §4, UNKNOWN) |
| **Anthropic** | no (paid) | `anthropic-ratelimit-requests-limit/-remaining/-reset`, `anthropic-ratelimit-tokens-limit/-remaining/-reset`, `anthropic-ratelimit-input-tokens-*`, `anthropic-ratelimit-output-tokens-*`, `anthropic-priority-*-tokens-*`, `retry-after` | `GET /v1/organizations/rate_limits` — **Admin API key**, returns **configured** limits (`{type, value}` pairs), never remaining; doc states *"The Admin API is unavailable for individual accounts."* | Headers yes; endpoint **NO** |
| **OpenAI** | no (paid) | `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`, `x-ratelimit-limit-project-tokens`, `x-ratelimit-remaining-project-tokens`, `x-ratelimit-reset-project-tokens`, `Retry-After` | none documented | Headers only |

**Providers that expose NOTHING, forcing purely reactive handling:**
**Google AI Studio (Gemini)**, **Mistral** (for an ordinary key), and
**Cerebras** (unverifiable — see §4). For these three there is no number a model
picker can honestly display before a request is made; the only signal is the
429 or 402 that arrives after it.

Note the shape of the OpenRouter win: `free_model_daily_requests` is
**account-wide**, which is precisely what `providers.py`'s OpenRouter note
already says (*"One account-wide cap covers every `:free` model"*) and what
`docs/0033` built the multi-account design around. One call per OpenRouter
account gives a true per-account remaining count.

---

## 3. INFERRED

**I1. The owner needs to build nothing for cross-provider history — but must
set one flag.** *Chain:* V2+V3 show the structural translation is complete for
both non-OpenAI providers in the pool; V4+V5 show the two provider-specific
poisons (Gemini thought signature, Anthropic thinking signature) are explicitly
handled; V6 shows the repair pass for orphaned/duplicated tool results exists
but returns early unless `litellm.modify_params` is true; the generated config
sets only `drop_params`. Therefore adding `modify_params: true` to
`litellm_settings` in `agentctl/control/proxy.py::build` converts a class of
400s into repaired requests. *Residual risk:* `modify_params` is by design
mutating — Case A injects a synthetic tool result the agent never produced, and
Case D silently discards a duplicate. For a system whose ledger records
effects, a silently invented tool result is a claim about the world that no
effect record backs. Recommend enabling it **and** logging when it fires, or
performing the equivalent repair in `agentctl` where the ledger can see it.
*Confidence:* high on the mechanism, medium on whether the owner wants
LiteLLM making that edit invisibly.

**I2. The realistic mid-conversation switch in this architecture is
group-to-group, not provider-to-provider — and it is already happening on
every retry.** *Chain:* the pool is a single model group `pool` with
`routing_strategy: simple-shuffle` and `num_retries: 5`. `simple-shuffle`
picks a deployment at random per request. So **turn N goes to
`openrouter-a3-m1` and turn N+1 to `gemini-a2-m0` already**, with no user
action, and has done since `docs/0034`. `agentctl`'s Seam A `TurnAffinity`
(`docs/0021` §3) pins only *within* an unresolved turn. Therefore
cross-provider history translation is not a feature the owner is contemplating
adding — it is a load-bearing property the system has been relying on in
production since the 42-deployment config existed. *Confidence:* high.
*Consequence:* if V6's repair pass matters, it has been silently absent for
every cross-provider hop so far.

**I3. A "model picker" over this pool is a category error unless the pool is
re-shaped.** *Chain:* V9 shows the only thing addressable by name from a
client is a model **group**, and there are two of them. `model_info.id` is not
a routable name — `docs/0034` §7 records the earlier bug where `fallbacks`
pointed at `model_info.id` values and *"those resolved to nothing"*. So
"pick source X, switch to another API of the same source" cannot be expressed
against today's config at all. To make sources selectable the generator would
have to emit **additional** `model_name` groups (e.g. `pool-gemini`,
`pool-openrouter`) alongside `pool`; LiteLLM permits one deployment to appear
in several groups only by duplicating the entry. *Confidence:* high on the
constraint, medium on the fix being desirable — every extra group is a smaller
failover pool, and `docs/0002` §5's "never silently spend" reasoning applies
equally to "never silently narrow your failover".

**I4. Continuing a tool-calling conversation on a non-tool model fails
silently or loudly depending on the provider, and neither is detected.**
*Chain:* V7 shows `drop_params` strips a parameter only when it is absent from
the **provider's** supported list, and V2/V10 show `tools` is present for every
OpenAI-compatible provider in the pool. So for `openrouter/`, `groq/`,
`cerebras/`, `mistral/` the `tools` array is forwarded and a model that cannot
use tools either ignores it (returning prose where the agent loop expects a
tool call → the loop stalls) or the upstream 400s. A 400 is not retried and not
cooled down (V8), so it surfaces. For a provider whose config omitted `tools`,
`drop_params: true` would strip it **with no error at all** — the
`records_with_cost: 0` failure shape of `docs/0021` §5, in a new place.
*Detection today:* none. `model_info.supports_function_calling` came back
`null` in the measured `/model/info` for models absent from the cost map — so
the proxy itself does not know either. *Confidence:* high.

**I5. Panel 1 cannot be answered honestly from the proxy without spending
quota.** *Chain:* V12 (health endpoints are process-level), V9+V15
(`/v1/models` is group-level and fails open), V14 (cooldown has no HTTP
surface), V16 (the Prometheus gauge is a lagging indicator, measured stale 15s
past expiry, and emits contradictory duplicate series), V13 (`/health` is
truthful but costs 42 completions). The only zero-cost, non-stale facts
available are: the proxy is up (V12), the pool's *shape* (V10), and what
happened on the **last real request** (V18's `x-litellm-model-id` plus any
forwarded `llm_provider-x-ratelimit-*`). Therefore the honest Panel 1 is
*"N deployments across M accounts are configured; the proxy is up; the last
request at HH:MM succeeded on `openrouter-a2-m1`"* — never a green light
asserting present capacity. *Confidence:* high. This is the `$0.00` lesson of
`docs/0021` §5 restated: a confident green that actually means "no data" is
worse than a blank.

**I6. `expose_router_debug_in_errors` is a cheap reactive channel.** *Chain:*
`router.py::async_function_with_fallbacks` appends fallback and cooldown debug
text to the exception message when `litellm.expose_router_debug_in_errors` is
set; measured with it off, the 500 body was only
`"...Received Model Group=pool\nAvailable Model Group Fallbacks=None"`. Turning
it on would let `agentctl` learn *which* deployments were cooled down at the
moment of a failure, at zero extra cost, from the error it already receives.
*Residual risk:* the message is user-facing and `mask_sensitive_structure` is
applied to fallbacks but the cooldown debug tuple carries
`exception_received` (masked to 50 chars by `SensitiveDataMasker` in
`CooldownCache`). Worth a read-through before enabling. *Confidence:* medium.

---

## 4. UNKNOWN

**U1. Cerebras rate-limit response headers.** The official page
`inference-docs.cerebras.ai/support/rate-limits` (fetched as `.md`, 2026-09-20)
documents the bucket model, TPM/TPH/TPD and the 429, and **does not list any
response headers**. Two T3 sources (`theneuralbase.com`) assert
`x-ratelimit-limit-requests-day`, `x-ratelimit-limit-tokens-minute`,
`x-ratelimit-remaining-requests-day`, `x-ratelimit-remaining-tokens-minute`.
Per the rules of engagement, T3 alone does not decide, so this is **UNKNOWN**,
not "yes with caveats". *Resolved by:* one authenticated request to
`https://api.cerebras.ai/v1/chat/completions` with `-i` and reading the actual
headers — but `docs/0034` §5 found Cerebras returns *"Payment required"* on
every completion, so the cheaper probe is `GET /v1/models` (which `probe.py`
already calls) with header capture added. That is a zero-token check.

**U2. Whether Mistral emits `X-RateLimit-Remaining` on ordinary chat
responses.** The Help Center article references checking it; no verbatim header
table was found in the API reference. **UNKNOWN.** *Resolved by:* capturing
response headers on one real Mistral completion, or on the existing
`GET /v1/models` probe.

**U3. Whether OpenRouter emits `X-RateLimit-*` on SUCCESS responses or only on
429.** The limits doc introduces them under "When rate limits are exceeded, the
error response includes...". **UNKNOWN** for the success path. *Resolved by:*
`-i` on one successful `:free` completion. Low stakes — `GET /api/v1/key` is
strictly better anyway.

**U4. Whether `modify_params: true` changes any currently-passing behaviour in
this repo.** The 502-test suite has never run with it set. *Resolved by:*
flipping it in a branch and running the suite plus the `experiments/` end-to-end
crash runs.

**U5. Whether `background_health_checks` could be made affordable.** In
principle a background loop at a long interval (e.g. hourly) would populate the
health state that `healthy_only=true` needs, at 42 completions/hour ≈ 1008/day
— which comfortably exceeds the free daily caps the whole project exists to
survive. Whether LiteLLM supports a per-deployment cheaper probe (`model_info.mode`,
`health_check_model`, `disable_background_health_check`) enough to bring that
under budget was not evaluated. *Resolved by:* reading
`proxy/health_check.py::_resolve_health_check_mode` against a costed plan; but
the prior is strongly negative and §7 assumes so.

**U6. Multi-worker cooldown visibility.** `CooldownCache` uses a `DualCache`;
with `redis_host` configured the cooldown entries are shared and **an external
process could read Redis keys `deployment:<model_id>:cooldown` directly**. That
would be a genuine, non-stale, zero-cost source — but it depends on running
Redis, which is outside the stated one-developer/student-budget constraint, and
reading another process's cache keys is a private-interface dependency
(`docs/0009` R1, upstream velocity). Not evaluated further. *Resolved by:*
deciding whether Redis is acceptable at all; if it ever is, re-open this.

---

## 5. Mechanism — how a cross-provider history translation actually works,
## and where it loses information

This section is the implementer-level walkthrough the brief asked for. The
canonical form is the OpenAI Chat Completions message list, because that is
what `agentctl` sends to the proxy and what every LiteLLM provider config
translates *from*.

### 5.1 The same two turns, in three schemas

**Canonical (OpenAI Chat Completions).** Four messages; the tool result is its
own message with its own role.

```jsonc
[
 {"role":"system","content":"You are a coding agent."},
 {"role":"user","content":"What's in README.md?"},
 {"role":"assistant","content":null,
  "tool_calls":[
    {"id":"call_abc","type":"function",
     "function":{"name":"read_file","arguments":"{\"path\":\"README.md\"}"}},
    {"id":"call_def","type":"function",
     "function":{"name":"stat","arguments":"{\"path\":\"README.md\"}"}}]},
 {"role":"tool","tool_call_id":"call_abc","content":"# agentctl\n..."},
 {"role":"tool","tool_call_id":"call_def","content":"4096 bytes"}
]
```

Tool definitions travel separately, as
`tools: [{"type":"function","function":{"name","description","parameters"}}]`,
where `parameters` is plain JSON Schema.

**Anthropic Messages API.** Three structural changes, not one.

```jsonc
{
 "system": "You are a coding agent.",            // hoisted OUT of messages
 "tools": [{"name":"read_file","description":"...",
            "input_schema":{"type":"object","properties":{...}}}],
 "messages":[
  {"role":"user","content":"What's in README.md?"},
  {"role":"assistant","content":[
    {"type":"tool_use","id":"call_abc","name":"read_file",
     "input":{"path":"README.md"}},            // object, not a string
    {"type":"tool_use","id":"call_def","name":"stat",
     "input":{"path":"README.md"}}]},
  {"role":"user","content":[                    // role CHANGES: tool -> user
    {"type":"tool_result","tool_use_id":"call_abc","content":"# agentctl\n..."},
    {"type":"tool_result","tool_use_id":"call_def","content":"4096 bytes"}]}
 ]
}
```

- `tools[].function.parameters` → `tools[].input_schema`, and the wrapper
  `{"type":"function","function":{...}}` is flattened away.
- `function.arguments` is a **JSON string**; `input` is a **parsed object**. A
  round trip through `json.loads`/`json.dumps` is mandatory and lossy in one
  specific way: key order and any non-canonical whitespace the model emitted are
  gone. Harmless for semantics, fatal for any hash of the raw arguments string
   — which matters here, because effect identity in this project is derived
  from action content.
- **Two parallel calls become two blocks in ONE assistant message; two results
  become two blocks in ONE user message.** This is the merge in
  `factory.py::anthropic_messages_pt`, which walks the list and coalesces
  consecutive `user`/`tool`/`function` messages. The N-messages-to-1-message
  collapse is why Case D (duplicate `tool_call_id`) is fatal on Anthropic and
  merely odd on OpenAI: Anthropic rejects with *"each tool_use must have a
  single result"*.
- `tool_use_id` must match `^[a-zA-Z0-9_-]+$`
  (`factory.py::_sanitize_anthropic_tool_use_id`). An id containing `:` or `/`
  is silently rewritten with `_`. **If your own code later matches the returned
  id against your recorded id, they no longer match.**
- The system prompt is a **top-level parameter**, not a message. There is
  exactly one of it. A conversation that interleaved several `system` messages
  mid-history loses that interleaving.

**Gemini `generateContent`.** Different again, and the differences are not
cosmetic.

```jsonc
{
 "systemInstruction":{"parts":[{"text":"You are a coding agent."}]},
 "tools":[{"functionDeclarations":[
    {"name":"read_file","description":"...",
     "parameters":{"type":"OBJECT","properties":{"path":{"type":"STRING"}}}}]}],
 "contents":[
  {"role":"user","parts":[{"text":"What's in README.md?"}]},
  {"role":"model","parts":[                       // "model", NOT "assistant"
    {"functionCall":{"name":"read_file","args":{"path":"README.md"},"id":"call_abc"}},
    {"functionCall":{"name":"stat","args":{"path":"README.md"},"id":"call_def"}}]},
  {"role":"user","parts":[                        // results go back as "user"
    {"functionResponse":{"name":"read_file","response":{"content":"# agentctl\n..."},"id":"call_abc"}},
    {"functionResponse":{"name":"stat","response":{"content":"4096 bytes"},"id":"call_def"}}]}
 ]
}
```

- `messages` → `contents`; each message is `{role, parts[]}`. The roles are
  `user` and **`model`** — there is no `assistant` and no `tool` role.
- **`functionResponse` is keyed by NAME, not by id, on pre-Gemini-3 models.**
  `types/llms/vertex_ai.py::FunctionResponse` marks `name` as `Required` and
  annotates `id` *"Supported on Gemini 3+; older Gemini models reject this
  field."* This is the deepest structural difference of the three: OpenAI and
  Anthropic correlate a result to a call by **id**; Gemini historically
  correlates by **function name**. LiteLLM reconstructs the name by scanning
  backwards for the matching `tool_call_id`
  (`factory.py::convert_to_gemini_tool_call_result`, the
  `last_message_with_tool_calls` loop) and raises
  `"Missing corresponding tool call for tool response message"` if it cannot.
  **Two parallel calls to the same function in one turn are therefore not
  distinguishable by name** — an agent that calls `read_file` twice in one turn
  is relying on `id`, i.e. on Gemini 3+.
- `response` must be an **object**. A plain string result is wrapped as
  `{"content": "..."}`; a result that happens to start with `{` or `[` is
  `json.loads`-ed and used directly. That is a **content-dependent
  transformation**: the same tool returning `"ok"` and returning `{"ok":true}`
  produce differently-shaped `response` objects.
- `Schema.type` is an **uppercase enum** (`"STRING"`, `"OBJECT"`, ...), not
  JSON Schema's lowercase. A JSON Schema feature with no Gemini equivalent
  (`oneOf`, `$ref`, `additionalProperties`) has nowhere to go.
- System prompt is `systemInstruction`, a `Content` of text parts only.

### 5.2 What must be rewritten, mechanically

| Canonical element | → Anthropic | → Gemini |
|---|---|---|
| `tools[].function.parameters` | `tools[].input_schema`, wrapper flattened | `tools[0].functionDeclarations[].parameters`, types UPPERCASED |
| `tool_calls[].function.arguments` (string) | `input` (object) — `json.loads` | `args` (object) — `json.loads` |
| `tool_calls[].id` | `tool_use.id`, sanitised to `[A-Za-z0-9_-]+` | `functionCall.id` on Gemini 3+; **dropped** and replaced by name-matching below |
| `role: "tool"` message | one `tool_result` block inside a **`user`** message | one `functionResponse` part inside a **`user`** content |
| N parallel calls | N `tool_use` blocks in ONE assistant message | N `functionCall` parts in ONE `model` content |
| N parallel results | N `tool_result` blocks in ONE user message | N `functionResponse` parts in ONE `user` content |
| `role: "system"` | top-level `system` parameter | top-level `systemInstruction` |
| `role: "assistant"` | `role: "assistant"` | `role: "model"` |
| tool result string | `content` (string or blocks) | `response` **object**, wrapped as `{"content": ...}` |

### 5.3 What is simply UNSAFE to carry, and why

1. **Anthropic `thinking` blocks.** The `signature` is cryptographically
   verified by Anthropic. A block whose signature is null/empty/missing — which
   is what you get from an open-weights reasoning model on Groq or OpenRouter —
   is rejected with a 400. It cannot be blanked or forged; it must be dropped.
   LiteLLM does this in `factory.py::_drop_unsignable_thinking_blocks`.
   *Loss:* the assistant's reasoning from the previous turn is gone. The model
   on the new provider sees the tool call but not the deliberation that
   produced it.

2. **Gemini thought signatures.** Gemini returns a `thoughtSignature` that must
   be replayed for the model to maintain its chain of thought across turns.
   Because the OpenAI wire format has nowhere to put it, LiteLLM smuggles it
   into the `tool_call_id`:
   `call_<uuid>__thought__<base64_signature>`
   (`factory.py::_encode_tool_call_id_with_signature`). If that id reaches
   Anthropic, `_sanitize_anthropic_tool_use_id` would happily accept it (it is
   already `[A-Za-z0-9_-]`-safe) and you would send a 200-character opaque id
   that no longer matches your recorded one; if it reaches a strict
   OpenAI-compatible provider it may exceed an id length limit. LiteLLM strips
   it in `utils.py::function_setup` when the target is not Gemini. *Loss:* the
   signature, and therefore Gemini's cross-turn reasoning continuity, the moment
   you leave Gemini. Coming *back* to Gemini 3, LiteLLM will substitute a dummy
   signature (`factory.py::_get_dummy_thought_signature`, documented as *"used
   when transferring conversation history from older models ... to gemini-3,
   which requires thought_signature"*).

3. **Provider-specific ids in general.** `call_abc` (OpenAI),
   `toolu_01A09...` (Anthropic) and Gemini's name-based correlation are three
   different identity schemes. Carrying an Anthropic `toolu_` id forward is
   harmless (it is just a string), but **your own** matching of ids must be
   done against the id you *sent*, never the id you get back, because both the
   Anthropic sanitiser and the Gemini signature-stripper rewrite it in flight.

4. **Cache breakpoints.** `cache_control` markers
   (`ChatCompletionCachedContent`, threaded through
   `factory.py::add_cache_control_to_content`) are Anthropic-specific prompt-cache
   breakpoints. Carrying them to a provider that does not implement prompt
   caching is at best ignored and at worst a 400 on an unknown field. They are
   also economically meaningless once the provider changes — which is
   `docs/0010` §6's point that rotation destroys a warm cache, restated at the
   message level.

5. **`server_tool_use` / `web_search_tool_result` blocks.** Anthropic
   server-side tool blocks (ids beginning `srvtoolu_`, reconstructed in
   `convert_to_anthropic_tool_invoke`) describe work Anthropic's own
   infrastructure did. No other provider can honour them; they describe a tool
   call the new provider cannot have made.

### 5.4 Where it breaks: tools and context

**A model that cannot do tools.** Two distinct failure modes (see I4):
if the provider config omits `tools` from `get_supported_openai_params`,
`drop_params: true` **silently deletes the tool definitions** and the model
answers in prose; the agent loop receives no `tool_calls`, does not act, and
nothing reports an error. If the provider config includes `tools` (which is the
case for every OpenAI-compatible provider in this pool), the array is forwarded
and the upstream returns a 400 — which is *not* retried across the pool and
*not* cooled down (V8), so it surfaces immediately. The loud failure is the good
one. The silent one is the `$0.00`-shaped hazard.

**A smaller context window.** The history was built to fit provider A. The
`pool` group spans models whose context windows differ by an order of
magnitude. Switching to a smaller one produces `ContextWindowExceededError`
(HTTP 400). Per V8 it is neither retried nor cooled down, and `agentctl`'s
config sets no `context_window_fallbacks`, so it surfaces as a hard 400 on the
turn. **This is the correct behaviour** — silently truncating an agent's
history would drop the record of actions already taken, which is exactly what
the effect ledger exists to prevent. Note the asymmetry: the same overlong
history will fail on *some* pool members and succeed on others, and with
`simple-shuffle` which one you get is random. The measured `/model/info` shows
`max_input_tokens` is available per deployment when the cost map knows the
model and `null` when it does not — so a pre-flight check is possible but not
universal.

---

## 6. Interface specification — model selection

Designed to obey the standing rule: every displayed number names its source and
the moment it was true, and a panel with nothing behind it says so.

### 6.1 Data, and the single source of truth for each field

| Field | Source of truth | Cost | Staleness |
|---|---|---|---|
| deployment list (`model_info.id`, `litellm_params.model`, `model_info.free`) | `GET {proxy}/model/info` | free, no key | config-load time; changes only on proxy restart |
| account label, provider | parsed from `model_info.id` (`provider-aN-mI`), cross-checked against `control/providers.py` | free | — |
| routable model names | `GET {proxy}/v1/models` (groups only: `pool`, `paid`) | free | — |
| proxy reachable | `GET {proxy}/health/liveliness` | free | instant |
| context window, tool support | `model_info.max_input_tokens`, `model_info.supports_function_calling` from `/model/info` | free | **may be `null`** — cost-map dependent |
| last deployment that served | `x-litellm-model-id` response header on the last real request | free (already paid for) | timestamped |
| upstream remaining rate limit | `llm_provider-x-ratelimit-remaining-*` / `x-ratelimit-remaining-*` on the last real request | free (already paid for) | timestamped; absent for most pool providers |
| OpenRouter free-tier daily quota | `GET https://openrouter.ai/api/v1/key` → `free_model_daily_requests.remaining`, per account | 1 metadata request per account, **zero tokens** | timestamped |
| key reachability / tier | existing `control/probe.py` (`live`/`rejected`/`limited`/`no-credit`/`unreachable`) | zero tokens | timestamped |
| cooldown state | **no honest zero-cost source** — see §6.4 | — | — |

Two rules follow from the table and must be enforced in code, not in the
docstring:

- **`model_info.id` is a label, not a routable name.** It must never be placed
  in a request's `model` field. `docs/0034` §7 already paid for this lesson.
- **Every displayed number carries `(source, observed_at)`.** A field with no
  observation renders as `—` with the reason, never as `0`.

### 6.2 Refresh policy

| Item | When |
|---|---|
| `/model/info`, `/v1/models` | on dashboard open, and on demand. Cache for the process lifetime; the config cannot change without a proxy restart. |
| `/health/liveliness` | on dashboard open. 2-second timeout. |
| `x-litellm-model-id` + forwarded rate-limit headers | **passively**, recorded by the existing Seam A callback (`agentctl_hook.proxy_handler_instance`) on every real request. Never polled. |
| OpenRouter `/api/v1/key` | on explicit user action only (`agentctl dash --refresh-quota`), never on a timer, and never automatically at startup. One request per OpenRouter account. |
| `control/probe.py` | on explicit user action (`agentctl doctor`), unchanged. |
| `GET /health` | **never automatically.** Behind an explicit flag with a warning stating the cost in requests, e.g. `agentctl dash --probe-live` → *"this will send 42 real completions, one per deployment, and consume free-tier quota. Continue? [y/N]"*. |

### 6.3 What it displays

```
  POOL          42 deployments across 18 accounts, 6 providers
                source: proxy /model/info at 14:31:02

  PROXY         up            source: /health/liveliness at 14:31:02

  LAST REQUEST  14:22:41  openrouter-a2-m1  (openrouter, account #2)  ok
                source: x-litellm-model-id on the response

  QUOTA
    openrouter#1   412 of 1000 free requests remaining
                   source: openrouter /api/v1/key at 14:19:55
    openrouter#2   —        not checked in this session (refresh to fetch)
    gemini#1       —        Gemini publishes no quota endpoint or header;
                            the only signal is the 429 when it arrives
    groq#1         —        no request yet this session; Groq reports
                            remaining only on a response header
    cerebras#1     —        no documented quota signal
    mistral#1      —        usage API requires an Admin key

  CAN I WORK RIGHT NOW?
    UNKNOWN — the proxy is up and 42 deployments are configured, but the
    router's cooldown state is not exposed on any endpoint, and a live
    probe would spend 42 requests of the quota it reports on. The last
    request, 8 minutes ago, succeeded.
```

The last block is the point. It is longer than a green dot and it is the only
version that is true.

### 6.4 What it says when it does not know

Three refusals, stated as rules:

- **No green "READY" light for present capacity.** The verdict vocabulary stays
  what `dash.py::_failover` already uses — `NONE` / `SINGLE ACCOUNT` /
  `MULTI-ACCOUNT` / `READY` — because those describe the **configured shape**,
  which `/model/info` genuinely establishes. They must not be re-read as a
  liveness claim, and the detail line should say so.
- **`—` plus a reason, never `0`.** `docs/0021` §5: an unpriced call and a free
  one must be different numbers. A quota of "unknown" and a quota of zero are
  likewise different, and the second is the one that stops work.
- **Every quota row names its provider's capability, not just its value.** The
  reason `gemini` shows `—` forever is not a bug to be fixed later; it is the
  finding. Saying *"Gemini publishes no quota endpoint or header"* teaches the
  user something true. A blank teaches nothing.

### 6.5 If a source picker is wanted anyway

To make "choose a source, switch to another API of the same source" expressible
at all (I3), `agentctl/control/proxy.py::build` would need to emit per-provider
groups in addition to `pool`:

```yaml
  - model_name: pool             # every free deployment: the failover pool
  - model_name: pool-openrouter  # same deployment, duplicated entry
```

That is a real cost, and it should be stated plainly to the owner: **selecting
a source narrows the failover pool from 42 deployments to that source's
share.** An OpenRouter-only selection is ~18 deployments behind one
account-wide daily cap, which is the exact failure `docs/0033` and the
multi-account design were built to escape. The picker should therefore show, at
the moment of selection, how many deployments and how many accounts the choice
leaves — and default to `pool`.

---

## 7. Verdict per part

### Part 1 — switching models mid-conversation: **CONFIGURE (do not build)**

Building a cross-provider history translator would duplicate
`litellm_core_utils/prompt_templates/factory.py`, a file whose Anthropic and
Gemini paths already handle role remapping, parallel-call coalescing, schema
transformation, id sanitisation, system-prompt hoisting, thought-signature
stripping and thinking-block dropping — including two hazards (V4, V5) the
owner would have discovered only after shipping. The whole change is:

```yaml
litellm_settings:
  drop_params: true
  modify_params: true        # <- enables factory.py::sanitize_messages_for_tool_calling
```

in `agentctl/control/proxy.py::build`, gated behind running the suite (U4), plus
a decision about whether LiteLLM silently injecting a synthetic tool result
(Case A) is acceptable to a system with an effect ledger — if it is not, do that
one repair in `agentctl` where the ledger can see it, and leave the rest to
LiteLLM.

**The strongest argument for BUILD, stated fairly:** `modify_params` makes
LiteLLM edit the agent's conversation invisibly, and `docs/0020`/`docs/0006`
exist because this project does not trust invisible edits to action history.
An `agentctl`-side normaliser would be auditable. The counter is decisive
anyway: you would still be running LiteLLM's translation underneath, so you
would own two normalisers instead of one, and the one you wrote would not know
about thought signatures.

### Part 2 — dashboard reading the live pool: **BUILD (narrowly) + SKIP (the rest)**

- **BUILD:** replace `dash.py::_providers`' environment-derived pool with
  `GET {proxy}/model/info` when a proxy URL is configured, falling back to the
  environment when it is not. This is a genuine upgrade — it reports what the
  running proxy actually loaded rather than what the environment implies, it
  costs nothing, needs no credential (V11), leaks no key (V10), and preserves
  `agentctl`'s own account labels. Add `/health/liveliness` as a reachability
  check. Estimated well under 80 lines including the "proxy not running" path.
- **BUILD (small):** have the existing Seam A callback record
  `x-litellm-model-id` and any forwarded `llm_provider-x-ratelimit-remaining-*`
  per request, so the dashboard can display the last observed truth with a
  timestamp. The hook already fires and already stamps `conversation:turn`
  (`docs/0021` §3); this is an additional field, not a new seam.
- **SKIP:** any live-capacity light. Cooldown has no HTTP surface (V14);
  `healthy_only` fails open and measures a different thing (V15); the
  Prometheus gauge was measured stale past cooldown expiry and emits
  contradictory duplicate series (V16); `/health` costs 42 completions (V13).
  Panel 1 answers **UNKNOWN with its reasons**, per §6.3.
- **SKIP:** budget/spend endpoints — unavailable without a database (V17), and
  the headers that exist describe a proxy virtual key that this deployment does
  not have.
- **Optional, cheap:** `expose_router_debug_in_errors: true` (I6) after a
  read-through, to learn cooldown state reactively from errors already received.

### Part 3 — free-tier quota display: **BUILD (OpenRouter only), SKIP (everything else)**

- **BUILD:** one function reading `GET https://openrouter.ai/api/v1/key` per
  OpenRouter account and surfacing `free_model_daily_requests.remaining` with a
  timestamp. `control/probe.py` already calls the sibling endpoint
  `/api/v1/auth/key` with the same auth, the same header discipline (key in a
  header, never a URL) and the same "never echo the key" rule, so this is an
  extension of an existing, tested path. Manual refresh only.
- **SKIP:** any attempt to display a quota number for Gemini, Cerebras or
  Mistral. There is no honest source (§2.3, U1, U2). These stay reactive: the
  429 or 402 is the signal, and the pool's job is to route around it. This is
  the same conclusion `providers.py`'s docstring reached independently — *"What
  the key is worth, you find out from the provider"* — now backed by a
  provider-by-provider audit of the primary documentation.
- **SKIP:** Anthropic's Rate Limits API and Mistral's Admin usage API. Both
  need an Admin key, Anthropic's is documented as *"unavailable for individual
  accounts"*, and both report configured or consumed figures rather than
  remaining.
- **Passive, free:** record Groq's `x-ratelimit-remaining-requests` /
  `x-ratelimit-remaining-tokens` when a response carries them (V18), displayed
  with the timestamp of the request that observed them. Never poll for them.

---

## 8. Sources, tiered and dated

### T1 — source code (read directly, `litellm==1.100.0`)

Installed at `C:\Users\csdee\openhands\.venv\Lib\site-packages\litellm`.
Permalink base `https://github.com/BerriAI/litellm/blob/v1.100.0/` (tag
resolution confirmed 2026-09-20).

- `litellm/litellm_core_utils/prompt_templates/factory.py` —
  `::convert_to_anthropic_tool_invoke`, `::convert_to_anthropic_tool_result`,
  `::convert_to_gemini_tool_call_result`, `::anthropic_messages_pt`,
  `::sanitize_messages_for_tool_calling`, `::_sanitize_anthropic_tool_use_id`,
  `::_is_unsignable_thinking_block`, `::_drop_unsignable_thinking_blocks`,
  `::_encode_tool_call_id_with_signature`, `::_get_thought_signature_from_tool`,
  `::_get_dummy_thought_signature`, `::THOUGHT_SIGNATURE_SEPARATOR`
- `litellm/utils.py` — `::function_setup` (the non-Gemini thought-signature
  strip), `::_remove_thought_signatures_from_messages`,
  `::get_optional_params` / `_check_valid_arg` (the `drop_params` rule)
- `litellm/llms/anthropic/chat/transformation.py` —
  `AnthropicConfig::translate_system_message`, `::_map_tools`,
  `::get_supported_openai_params`
- `litellm/llms/vertex_ai/gemini/transformation.py` — `::_transform_system_message`
- `litellm/types/llms/vertex_ai.py` — `ContentType`, `PartType`, `FunctionCall`,
  `FunctionResponse`, `Tools`, `SystemInstructions`, `Schema`
- `litellm/types/llms/openai.py` — `ChatCompletionToolParam`,
  `ChatCompletionAssistantToolCall`, `ChatCompletionToolMessage`,
  `ChatCompletionThinkingBlock`
- `litellm/llms/openai/chat/gpt_transformation.py` —
  `OpenAIGPTConfig::get_supported_openai_params`
- `litellm/router.py` — deployment-id preservation (`declared_id`),
  `::_get_healthy_deployments`, `::async_function_with_fallbacks`
- `litellm/router_utils/cooldown_cache.py` — `CooldownCache`,
  `CooldownCacheValue`, `::get_active_cooldowns`, `::get_cooldown_cache_key`
- `litellm/router_utils/cooldown_handlers.py` — `::_is_cooldown_required`,
  `::_should_cooldown_deployment`, `::_set_cooldown_deployments`,
  `::_get_cooldown_deployments`
- `litellm/router_utils/cooldown_callbacks.py` — `::router_cooldown_event_callback`
- `litellm/integrations/prometheus.py` — `litellm_deployment_state`,
  `litellm_deployment_cooled_down`, `::set_deployment_healthy`,
  `::set_deployment_partial_outage`, `::set_deployment_complete_outage`,
  `litellm_remaining_requests_metric` / `litellm_remaining_tokens_metric` and
  the "only fire for OpenAI / Anthropic / Azure" comment
- `litellm/proxy/proxy_server.py` — `::model_list` (`/v1/models`),
  `::model_info_v1` (`/model/info`), `::_get_proxy_model_info`, prometheus mount
- `litellm/proxy/health_endpoints/_health_endpoints.py` — `::health_endpoint`,
  `::health_liveliness`, `::health_readiness`, `::_get_health_readiness_details`
- `litellm/proxy/health_check.py` — `::perform_health_check`,
  `::filter_deployments_by_id`, `::_get_random_llm_message`
- `litellm/proxy/utils.py` — `::create_model_info_response`
- `litellm/proxy/common_utils/openai_endpoint_utils.py` —
  `::remove_sensitive_info_from_deployment`
- `litellm/proxy/common_request_processing.py` —
  `ProxyBaseLLMRequestProcessing::get_custom_headers`
- `litellm/proxy/auth/user_api_key_auth.py` — the `master_key is None` path
- `litellm/litellm_core_utils/llm_response_utils/get_headers.py` —
  `::get_response_headers`, `::_get_llm_provider_headers`
- `litellm/litellm_core_utils/core_helpers.py` — `::process_response_headers`
- `litellm/types/proxy/model_listing.py` — `ModelInfoResponse`

Project source (`github.com/csdeepak/HandCode`, working tree at commit
`6bb26d0`, 2026-09-20):
`agentctl/control/providers.py`, `agentctl/control/dash.py`,
`agentctl/control/proxy.py::build`, `agentctl/control/probe.py::ENDPOINTS`,
`proxy/proxy_config.yaml`, `docs/0021` §5, `docs/0033`, `docs/0034` §§2,5,7,
`docs/0037`.

### T1 — official API references (all fetched 2026-09-20)

- Anthropic, *Rate limits* — the `anthropic-ratelimit-*` header table.
  https://platform.claude.com/docs/en/api/rate-limits
- Anthropic, *Rate Limits API* — `/v1/organizations/rate_limits`, Admin key
  required, *"The Admin API is unavailable for individual accounts."*
  https://platform.claude.com/docs/en/manage-claude/rate-limits-api
- Anthropic, *Tool use with Claude* — `input_schema`, `tool_use`,
  `tool_result`, `tool_use_id`, `disable_parallel_tool_use`.
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
- OpenAI, *Rate limits* — the `x-ratelimit-*` header table; no quota endpoint.
  https://developers.openai.com/api/docs/guides/rate-limits
- OpenAI, *Function calling* — `arguments` is a JSON string.
  https://developers.openai.com/api/docs/guides/function-calling
- Google, *Gemini API — Rate limits* — **no headers, no quota endpoint
  documented**; directs to the AI Studio web page.
  https://ai.google.dev/gemini-api/docs/rate-limits
- Google, *Gemini API — generateContent* — `Content.role` ∈ {user, model},
  `parts[]`, `functionCall`, `functionResponse`, `Tool.functionDeclarations`,
  `systemInstruction`. https://ai.google.dev/api/generate-content
- Groq, *Rate limits* — `x-ratelimit-limit-requests`,
  `x-ratelimit-remaining-requests`, `x-ratelimit-limit-tokens`,
  `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-*`, `retry-after`; no
  endpoint. https://console.groq.com/docs/rate-limits
- OpenRouter, *API key limits* — `GET /api/v1/key`, `limit`, `limit_remaining`,
  `free_model_daily_requests{used,limit,remaining}`, `is_free_tier`; normal
  inference key. https://openrouter.ai/docs/api-reference/limits
- OpenRouter, *Get credits* — `/credits` requires a **Management key**.
  https://openrouter.ai/docs/api-reference/get-credits
- Mistral, *Usage metrics (Admin API)* — `https://api.mistral.ai/v1/admin/usage`,
  Admin API key from the Backoffice, consumed usage only.
  https://docs.mistral.ai/admin/admin-api/usage-metrics
- Mistral, *Usage and limits* — points at the Admin Panel; no headers given.
  https://docs.mistral.ai/admin/billing-usage/usage-limits
- Cerebras, *Rate Limits* — token buckets, TPM/TPH/TPD, 429 behaviour;
  **no response-header table**. https://inference-docs.cerebras.ai/support/rate-limits
- LiteLLM, *Prometheus* — `/metrics`, `litellm_deployment_state`
  (0/1/2), `prometheus_client` install, no premium gate stated.
  https://docs.litellm.ai/docs/proxy/prometheus

### T1 — measurements (this session, 2026-09-20)

Local LiteLLM 1.100.0 proxy, three fake deployments, `api_base`
`http://127.0.0.1:9/v1`, no provider key, zero quota consumed. Transcripts are
inline at V9, V10, V12, V13, V15, V16.

- `/v1/models` returns groups only (2 rows for 3 deployments)
- `/model/info` returns 3 rows, `model_info.id` preserved, no `api_key`
- `/health/readiness` → `{"status":"healthy","db":"Not connected"}`
- `/health/liveliness` → 200, 12 bytes
- `/health` → per-deployment `model_id` + `exception_status`, one live
  completion each
- `/v1/models?healthy_only=true` unchanged after failures (fails open)
- `/metrics` → 404 without `prometheus_client`; with it, `litellm_deployment_state`
  showing duplicate contradictory series, and still `2.0` **15 seconds after
  cooldown expiry with no traffic**

### T3 — cited but decisive of nothing

- `theneuralbase.com` (Cerebras capacity-planning / higher-limits pages) assert
  `x-ratelimit-limit-requests-day`, `x-ratelimit-remaining-tokens-minute` and
  similar Cerebras headers. **Not corroborated by Cerebras' own documentation**,
  therefore recorded as UNKNOWN (U1), not as a finding.

### Staleness flags

Nothing load-bearing here is older than 12 months. The provider documentation
was all fetched on 2026-09-20. The LiteLLM behaviours are pinned to 1.100.0 and
will drift — `docs/0009` R1 (upstream velocity) applies, and the specific
things most likely to move are the `healthy_only` semantics (new enough to be
documented defensively in the handler's own docstring) and the Gemini
`functionResponse.id` support boundary, which the source already annotates as
version-dependent. `providers.py`'s own warning stands: tier and quota facts
about free providers go stale in weeks, and none of them are written into code
by this specification.
