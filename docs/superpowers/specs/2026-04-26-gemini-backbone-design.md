# Gemini Backbone Design For Advisory Agents

## Summary

This design adopts `gemini-2.5-flash-lite` as the primary LLM backbone for the advisory-agent system, while allowing explicit per-agent overrides and selective fallback to stronger models or secondary providers. The primary goal is cost efficiency, including support for non-paid usage tiers, without forcing a single model onto tasks that are better handled by deterministic code or higher-capability models.

The design introduces a centralized model selection layer instead of embedding provider logic inside each agent. This keeps agent responsibilities clear, makes cost and escalation behavior auditable, and provides a stable path to expand from the current advisory-focused repository into the broader ingestion and conflict-resolution architecture described in the admission counseling design document.

## Problem Statement

The current project has multiple agent responsibilities with different failure costs:

- profile extraction and follow-up prompting
- deterministic retrieval and filtering
- recommendation reasoning
- policy enforcement
- user-facing explanation

The broader target architecture also includes:

- extraction and normalization from heterogeneous sources
- validation against legal and institutional rules
- conflict detection and conflict resolution across evidence

Using one low-cost model uniformly across all of these steps would create avoidable reliability risk. At the same time, using a stronger model everywhere would weaken the main reason for choosing Gemini: low cost and usable free-tier quotas.

The system therefore needs:

- one cheap default model
- explicit per-agent model overrides
- rule-based retry and escalation
- deterministic handling where LLMs are not the right tool
- centralized observability for cost and failure analysis

## Goals

- Make `gemini-2.5-flash-lite` the default model for LLM-backed agents.
- Allow per-agent model overrides through configuration.
- Support selective fallback to stronger models and, for chosen agents, a second provider.
- Keep deterministic tasks deterministic wherever possible.
- Centralize retry, fallback, parsing, and telemetry behavior in one inference layer.
- Preserve current agent boundaries and align with the future multi-agent architecture.

## Non-Goals

- Building a dynamic runtime router that chooses models from free-form heuristics.
- Replacing deterministic retrieval, policy validation, or evidence ranking with LLM-only logic.
- Redesigning the entire admission workflow in this step.
- Committing to a specific fallback provider before implementation planning.

## Recommended Approach

The system should use a central model registry and per-agent inference policies.

This is preferred over a single global model with ad hoc exceptions because hardcoded overrides spread routing logic across many files and are difficult to test. It is also preferred over a capability-tier router because the current and planned architecture is organized around named agent responsibilities, and per-agent configuration is easier to reason about than a more abstract task taxonomy.

## Architecture

### Overview

Agents should not call model providers directly. Each agent should submit inference requests through a shared gateway that resolves model choice, retry behavior, structured-output settings, fallback rules, and logging.

Core components:

- `ModelRegistry`
  - Stores default provider/model settings.
  - Stores per-agent overrides.
  - Stores fallback provider/model mappings for eligible agents.
- `InferencePolicy`
  - Defines retry and escalation behavior per agent.
  - Defines output mode such as `json`, `classification`, or `free_text`.
  - Defines whether an agent is allowed to use fallback.
- `LLMGateway`
  - Single entrypoint for inference requests.
  - Applies policy, executes provider calls, validates structure, performs retries, and triggers fallback when allowed.
- `InferenceResult`
  - Normalized response object containing content, parsed data, provider/model metadata, failure classification, and confidence or uncertainty signals.

### Request Flow

1. An agent creates an inference request with `agent_name`, `task_type`, expected output mode, and prompt payload.
2. The `LLMGateway` reads the active policy from `ModelRegistry` and `InferencePolicy`.
3. The gateway calls the primary model, usually `gemini-2.5-flash-lite`.
4. The gateway validates the result against the required structure and policy checks.
5. If the failure is structural, the gateway retries once on the same model with stricter constraints.
6. If the failure is semantic or confidence-related and the agent allows escalation, the gateway calls the configured fallback model.
7. The gateway returns a normalized `InferenceResult` to the agent.
8. If no trustworthy result is available, the gateway returns an explicit uncertainty state instead of pretending success.

## Agent Mapping

### Current Advisory Agents

- `profile_agent`
  - Primary model: `gemini-2.5-flash-lite`
  - Purpose: extract structured student profile data, detect missing fields, support follow-up questioning
  - Escalation: uncommon
  - Reasoning: errors are usually recoverable through additional interaction

- `retrieval_agent`
  - Primary path: deterministic retrieval and constraint filtering
  - LLM usage: optional query interpretation or semantic reformulation only
  - Reasoning: hard eligibility filters should not depend on a generative model

- `reasoning_agent`
  - Primary model: `gemini-2.5-flash-lite`
  - Fallback: enabled
  - Reasoning: recommendation ranking and tradeoff synthesis are useful cheap-model workloads, but this is a higher-risk reasoning step that needs a stronger escape hatch

- `policy_agent`
  - Primary path: deterministic rules first
  - LLM usage: limited to ambiguous policy interpretation and explanation support
  - Fallback: enabled for ambiguity cases
  - Reasoning: legal and policy compliance should remain rule-led, not model-led

- `explanation_agent`
  - Primary model: `gemini-2.5-flash-lite`
  - Fallback: usually disabled
  - Reasoning: explanation is a good low-cost workload once the underlying recommendation is already validated

### Future Agents From The Broader Architecture

- `extraction_agent`
  - Primary model: `gemini-2.5-flash-lite`
  - Fallback: enabled for complex PDFs, tables, or messy sources

- `normalization_agent`
  - Primary path: deterministic transforms where possible
  - LLM usage: optional support for schema alignment or ambiguous field mapping

- `validation_agent`
  - Primary path: deterministic rule checks

- `conflict_detection_agent`
  - Primary path: deterministic comparison of fields, timestamps, and source provenance

- `evidence_agent`
  - Primary path: deterministic evidence retrieval
  - LLM usage: optional summarization only

- `comparison_agent`
  - Primary path: deterministic authority ranking and evidence scoring
  - LLM usage: optional interpretive support

- `resolution_agent`
  - Primary model: `gemini-2.5-flash-lite`
  - Fallback: enabled
  - Reasoning: conflict resolution is one of the highest-risk reasoning tasks, so stronger fallback is important here

## Failure Handling And Escalation

### Failure Categories

- `STRUCTURE_FAILURE`
  - malformed JSON
  - missing required fields
  - schema mismatch
  - incomplete structured output

- `SEMANTIC_FAILURE`
  - contradictory reasoning
  - unsupported recommendation
  - weak policy interpretation
  - conflict-resolution rationale that does not support the chosen outcome

- `CONFIDENCE_FAILURE`
  - explicit model uncertainty
  - downstream validation checks disagree with the answer
  - incomplete or conflicting evidence prevents a trustworthy conclusion

### Escalation Rules

- Retry on the same model:
  - structured output is malformed
  - required keys are missing
  - output format is recoverable through a stricter schema reminder

- Escalate to a stronger model:
  - `reasoning_agent` cannot justify ranking or recommendation confidence
  - `policy_agent` encounters ambiguous policy text
  - `resolution_agent` cannot resolve evidence conflict cleanly
  - `extraction_agent` fails on difficult source structure

- Do not auto-escalate:
  - explanation-only quality issues
  - routine profile gaps that should trigger user follow-up
  - retrieval failures caused by missing user data rather than model weakness

### Budget Controls

- per-request cap on total fallback invocations
- per-agent cap on retries and escalations
- optional provider-level daily quota bucket
- logging for every retry and escalation reason

### User-Facing Uncertainty Behavior

When the system cannot produce a trustworthy answer, it must return uncertainty explicitly. The response should state:

- what is known
- what is conflicting or ambiguous
- what additional user data is needed, if applicable
- when the student should verify directly with the university

In this domain, explicit uncertainty is safer than fabricated confidence.

## Configuration

The first implementation should use static configuration plus rule-based escalation, not a dynamic router.

Recommended configuration concepts:

- `default_model`
- `agent_overrides`
- `fallback_models`
- `retry_limits`
- `escalation_rules`
- `structured_output_mode`
- provider-specific generation settings for each task type
- budget caps

Provider credentials should remain provider-specific, but the rest of the system should read normalized settings from one central configuration surface.

## Observability

Because cost efficiency is the main reason for selecting `gemini-2.5-flash-lite`, inference telemetry is mandatory.

The system should log:

- agent name
- task type
- provider and model used
- whether a retry occurred
- whether fallback occurred
- reason for retry or escalation
- token usage if exposed by the provider
- schema or validation failures
- final success or uncertainty status

This data is necessary to determine whether the cheap backbone is actually saving money or just causing repeated retries and silent escalation.

## Testing Strategy

Testing should be agent-level and gateway-level, not only end-to-end.

Recommended test coverage:

- unit tests for model selection by agent
- unit tests for retry and fallback policy decisions
- schema-validation tests for structured outputs
- mocked gateway tests for each current advisory agent
- regression fixtures for:
  - incomplete student profiles
  - unsupported recommendation paths
  - policy ambiguity
  - conflicting quota or requirement evidence

If a final answer is wrong, the system should make it possible to determine whether the failure came from profile extraction, retrieval, reasoning, policy enforcement, or explanation.

## Rollout Order

1. Add a central model registry and gateway.
2. Route current advisory agents through the gateway.
3. Keep retrieval and policy enforcement deterministic wherever possible.
4. Enable stronger fallback only for `reasoning_agent` and `policy_agent` first.
5. Expand the same backbone pattern later to ingestion and conflict-resolution agents.

## Tradeoffs

### Benefits

- preserves cheap default inference for most generative workloads
- avoids overusing stronger models
- keeps agent responsibilities clean
- makes escalation behavior testable and auditable
- supports future architecture expansion without replacing the model layer

### Costs

- adds an abstraction layer before more features ship
- requires discipline to keep deterministic logic out of the gateway
- requires better telemetry and tests than a direct provider call approach

## Decision Summary

The recommended design is:

- default backbone: `gemini-2.5-flash-lite`
- configuration style: static defaults plus rule-based escalation
- control model: centralized registry and gateway
- fallback strategy: selective per-agent escalation, with secondary provider support where justified
- reliability posture: deterministic logic first, LLMs for interpretation, synthesis, and explanation

This design is intentionally narrow in scope. It solves model selection, cost control, and escalation behavior without forcing a full architectural rewrite of the existing advisory flow.
