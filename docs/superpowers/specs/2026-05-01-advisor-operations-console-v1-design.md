# Student Advisory Chat V1 Design

## Summary

This design defines the first ready-to-use student-facing product surface for the advisory-agent repository: an anonymous web chat for students and parents that progressively builds a student profile through conversation and then runs the existing advisory workflow to produce recommendations.

The goal is not to build a generic chatbot or a full conversational platform rewrite. The first release should add a session-oriented product layer on top of the current advisory graph so users can describe their situation in natural language, answer targeted follow-up questions, and receive grounded advisory results without logging in.

The existing advisory graph and Gemini inference backbone remain the execution core. This phase adds the chat UI, anonymous session handling, profile-state management, and run orchestration needed to make that core usable by students and parents.

## Problem Statement

The current repository contains agent orchestration, deterministic retrieval and policy logic, Gemini-backed inference services, and test coverage for the advisory flow. What it does not yet provide is a student-usable product surface.

Today, the system is still effectively a codebase plus demo entrypoint:

- there is no public chat interface
- there is no anonymous session model
- there is no stored multi-turn conversation state
- there is no product layer that decides when to ask follow-up questions versus when to run the full advisory workflow
- there is no user-facing presentation layer for recommendations, caveats, and refinement loops

That means the system can demonstrate advisory logic, but it cannot yet support a real student or parent conversation.

## Goals

- Ship a student/parent-facing web chat.
- Allow users to start without login.
- Build structured profile state progressively from natural-language conversation.
- Ask focused follow-up questions when critical profile fields are missing.
- Run the full advisory workflow only when profile state is sufficiently complete.
- Return recommendations, explanations, caveats, and refinement paths in chat.
- Preserve the existing advisory graph as the execution core instead of rewriting it.

## Non-Goals

- Building an internal operator console in this phase.
- Adding user accounts, authentication, or cross-device saved history.
- Redesigning the advisory graph into a fully turn-by-turn conversational agent runtime.
- Combining this release with ingestion operations or admin tooling.
- Supporting every possible chat use case beyond admission advisory.

## Recommended Approach

The system should be productized as a hybrid advisory session layer on top of the existing graph.

This is preferred over a thin chat shell because the current advisory flow depends on reasonably complete profile data, and a naive message-in answer-out wrapper would feel brittle and shallow. It is also preferred over a full conversational re-architecture because that would expand the phase into a rewrite instead of a productization step.

The first release should therefore focus on one high-value public job:

- let a student or parent begin with freeform chat
- extract usable profile fields incrementally
- ask one targeted follow-up question at a time
- launch a background advisory run once enough information is known
- present results in a conversational format and allow refinement

## Architecture

### Overview

The product should use four primary layers:

- `chat web app`
  - Provides the public student/parent chat experience.
- `session API`
  - Owns anonymous session lifecycle, message handling, profile-state persistence, and run triggers.
- `advisory session layer`
  - Decides whether to ask a follow-up question, update profile state, or launch a full advisory run.
- `existing advisory core`
  - Executes the current graph, retrieval logic, policy logic, and Gemini-backed inference services.

The chat UI must not call the advisory graph directly on every message. The session layer should absorb conversational turns, maintain state, and decide when enough information exists to justify a full advisory run.

### Core Modules

- `sessions`
  - Handles anonymous session lifecycle and metadata.
- `messages`
  - Stores user and assistant chat turns.
- `profile_state`
  - Stores the progressively built structured student profile and missing critical slots.
- `advisory_runs`
  - Stores background executions of the full graph for a session.
- `artifacts`
  - Stores recommendations, evidence, warnings, uncertainty reasons, and final explanation payloads.

### Execution Model

1. A user opens the site and starts an anonymous session.
2. The user sends a freeform message describing goals, scores, constraints, or interests.
3. The session API stores the message and passes it to the advisory session layer.
4. The session layer updates structured profile state from the new input.
5. If critical profile fields are still missing, the assistant returns one focused follow-up question.
6. If the profile is sufficiently complete, the backend creates an advisory run.
7. A background worker executes the existing advisory graph.
8. When the run completes, the session layer posts the result back into the conversation and updates the latest session artifacts.

## Conversation Design

### Primary User Flow

1. User opens the chat page.
2. User describes their situation in natural language.
3. System extracts profile data from the message.
4. System asks one focused follow-up question if critical fields are missing.
5. User replies and profile state is updated.
6. Once enough information is known, the backend launches a full advisory run.
7. The assistant returns recommendations, reasoning, caveats, and next-step guidance in chat.
8. The user can refine the result with more details, which may trigger a new run tied to the same session.

### Critical Profile Slots

The first release should treat these as the default high-value slots:

- admission year
- score or score estimate
- preferred majors or interests
- geography preference
- hard constraints if stated, such as budget or language requirement

The session layer should tolerate partial inputs, but it should not run the full advisory flow while core fields remain too incomplete to support a useful answer.

### UX Rules

- ask only one follow-up question at a time
- do not run the full advisory graph after every user message
- show what the system has understood so far
- if confidence is low, explain what is missing rather than fabricating certainty
- if the user changes important facts, create a new advisory run rather than silently mutating the prior result

The intended experience is progressive advisory intake through chat, not a generic assistant that improvises around missing data.

## Data Design

### Session Record

Each `Session` should contain:

- session identifier
- client-visible anonymous session token or key
- current session status
- latest structured profile state
- pointer to latest advisory result
- created and updated timestamps

### Message Record

Each `Message` should contain:

- message identifier
- parent session identifier
- role such as user or assistant
- message content
- optional message type metadata such as follow-up question, result, or system status
- created timestamp

### Advisory Run Record

Each `AdvisoryRun` should contain:

- run identifier
- parent session identifier
- run status
- snapshot of profile state at run start
- step timeline
- structured artifacts from the advisory graph
- warnings and uncertainty reasons
- failure details
- provider and model metadata for auditability
- created, started, and completed timestamps

### Storage Model

The recommended persistence model is a relational database with JSON fields for profile state and advisory artifacts.

This is preferred because the product needs reliable storage for session and run lifecycle data, while conversationally extracted profile structures and recommendation artifacts will evolve as the product matures.

## Integration With Existing Advisory Core

This phase should reuse the current advisory graph and supporting services rather than introducing a second recommendation engine.

Required integration rules:

- the session layer is responsible for deciding when to invoke the graph
- each advisory run starts from the current persisted profile state, not directly from raw chat text
- the full graph remains the source of truth for recommendations
- each completed run writes artifacts back to session storage
- follow-up and uncertainty signals from the existing policy and inference layers must remain visible in the user-facing result

The session adapter should be thin. Its purpose is to translate conversational state into graph-ready structured input and to translate graph output into chat-appropriate responses.

## Error Handling And Reliability

### Failure Rules

- if parsing or profile extraction from a message is weak, the system should ask a clearer follow-up question instead of surfacing raw errors
- if an advisory run fails, the run is marked `failed` and the user sees a recovery message in chat
- failed runs must remain stored for debugging and analysis
- prior successful conversation history and artifacts remain preserved

### Uncertainty Rules

- if the system lacks enough information, it should explicitly ask for the minimum next missing detail
- if policy ambiguity or evidence uncertainty exists, the assistant should explain that clearly in user language
- if no trustworthy recommendation can be produced yet, the system should prefer asking for clarification over pretending confidence

### Session Continuity Rules

- anonymous sessions should survive page refresh on the same device
- session reset should create a clean new session
- refinements after a recommendation should create a new advisory run under the same session history

## UI Scope

The first release should contain a minimal but usable public chat experience:

- landing and chat page
- chat transcript with user and assistant turns
- lightweight profile summary panel showing what the system currently understands
- recommendation card or result panel for latest advisory output
- loading and analyzing states while a run is active
- session reset action

The UI should feel conversational, but it should also make the system’s structured understanding visible so users can correct misunderstandings early.

## Testing Strategy

Testing for this phase should cover session lifecycle, decision logic between follow-up and run launch, and the public chat critical path.

Recommended coverage:

- API tests for anonymous session creation and message flow
- state-machine tests for follow-up versus advisory-run trigger decisions
- integration test for a multi-turn chat that ends in one advisory result
- regression test ensuring changed profile facts create a new run instead of mutating old output
- UI smoke tests for new session, follow-up exchange, run progress, and result display

The test boundary should prove that the product layer preserves the reliability work already done in the advisory graph while making it usable through chat.

## Rollout Order

1. Add persistence models for sessions, messages, profile state, and advisory runs.
2. Add session and message API endpoints.
3. Add the advisory session layer for follow-up versus run-trigger decisions.
4. Add background job execution for full advisory runs.
5. Persist artifacts and latest result summaries back to the session.
6. Build the public chat UI with profile summary and recommendation display.

## Tradeoffs

### Benefits

- turns the repository into a usable public-facing product
- reuses the existing advisory and Gemini backbone work
- improves answer quality by collecting structured data before running the full workflow
- keeps the phase focused on one high-value user journey
- avoids premature redesign of the advisory core

### Costs

- introduces new session-state and chat-product logic
- requires persistence and background orchestration that the demo flow did not need
- delays authenticated history, operator tooling, and broader admin features to later phases

## Decision Summary

The recommended next phase is:

- phase name: `Student Advisory Chat V1`
- user: student or parent
- workflow: hybrid chat with progressive profile capture and targeted follow-up
- execution mode: anonymous sessions first, with background advisory runs
- product shape: public chat UI, session API, advisory session layer, and existing graph as core
- reliability posture: ask for clarification when profile data is insufficient and preserve run history per session

This design intentionally avoids operator tooling, authentication, and full conversational-runtime redesign. The goal of the phase is narrower and more practical: make the existing advisory system usable by students and parents through a guided chat experience.
