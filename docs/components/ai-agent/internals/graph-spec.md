# AI Agent — Graph and State Machine Specification

This document is the visual companion to:

- [`../requirements.md`](../requirements.md)
- [`../design.md`](../design.md)

If anything here contradicts the requirements doc, the requirements doc wins.

## Reading Guide

The diagrams in this document answer four durable questions:

1. what the agent system looks like overall
2. what the current planning shell looks like
3. what one agent run does internally
4. how authority expands in later phases

## 1. Top-Level System Map

```mermaid
flowchart TB
    subgraph Edge["Operator Edges"]
        TXT[Text Terminal]
        VC[Voice Adapter<br/>future]
        ES[E-Stop 🔒<br/>synchronous bypass]
    end

    subgraph Surfaces["Session Surfaces"]
        CHAT[AIChatService<br/>session + persistence]
        SHELL[PlanningShellGraph<br/>durable HITL wrapper]
        SCHED[Task Scheduler<br/>future]
    end

    subgraph Core["Shared Agent Runtime"]
        LOOP[AgentLoopRuntime<br/>bounded loop]
        CTX[ContextManifest<br/>compact context + manifest]
        REG[ToolRegistry<br/>tier · scope · side_effects]
        POL[PolicyEngine<br/>grants · freshness · budget]
        TRC[AgentTraceStore<br/>JSONL trace per run]
        MEM[MemoryStore<br/>layered memory]
        PRV[ProviderRegistry<br/>role-routed]
    end

    subgraph Roles["Specialist Roles"]
        PL[planner]
        CR[critic]
        RS[researcher]
        MN[monitor]
        RP[reporter]
        EX[executor]
    end

    subgraph Auth["Backend Physical Authority"]
        MX[mission_execution<br/>revisions · CAS · rollback]
        STG[CommandStaging]
        SIM[Simulator]
        APH[Autopilot]
        HW[Rover Hardware]
    end

    TXT --> CHAT
    TXT --> SHELL
    VC --> CHAT
    VC --> SHELL
    ES ===> HW

    CHAT --> LOOP
    SHELL --> LOOP
    SCHED --> LOOP

    LOOP --- CTX
    LOOP --- REG
    LOOP --- POL
    LOOP --- TRC
    LOOP --- MEM
    LOOP --- PRV

    LOOP -.-> PL & CR & RS & MN & RP & EX

    SHELL ==> MX
    EX -.-> STG
    STG -.-> SIM
    STG -.-> APH
    APH -.-> HW
    MN -.-> APH
```

Three load-bearing boundaries:

- reasoning lives in `AgentLoopRuntime`
- capability enforcement lives in `ToolRegistry` plus `PolicyEngine`
- physical authority lives in backend services, autopilot, and hardware rather
  than in the model loop

## 2. Current Planning Shell

The planner loop is the sole planning core. Deterministic validation and
approval remain outside free-form model reasoning.

```mermaid
flowchart TB
    S([START]) --> CAP[capture_request]
    CAP --> INIT[retrieve_current_context<br/>compact snapshot + manifest]
    INIT --> LP[planner_loop_node<br/>AgentLoopRuntime · role=planner]
    LP -.-> PCL[prepare_clarification ⏸<br/>resume into LP]
    PCL -.-> LP
    LP -.-> CR[critic_loop_node<br/>optional future]
    LP --> VD[validate_draft 🔒]
    CR --> VD
    VD --> ST["store_draft<br/>(mission_execution.create_proposal)"]
    ST --> AP[request_planning_shell_approval ⏸]
    AP --> D{approved?}
    D -- yes --> RA["record_approval<br/>(mission_execution.approve + export)"] --> FN[finalize_response]
    D -- no --> RJ["record_rejection<br/>(mission_execution.reject)"] --> FN
    FN --> E([END])
```

Durable properties:

- `validate_draft` is the last deterministic gate before storage
- draft approval is the only operator approval at this planning tier
- canonical mission storage lives in `mission_execution`
- clarification resumes the same planning loop rather than switching to a
  separate planning path

## 3. AgentLoopRuntime — Internal State Machine

Every chat run, planner run, specialist run, and future voice/task/monitor
invocation passes through this machine.

```mermaid
stateDiagram-v2
    [*] --> Seed

    Seed --> Plan: system + manifest + user
    Plan --> Decide: model.ainvoke
    Decide --> Final: no tool_calls
    Decide --> Guard: tool_calls present

    Guard --> Act: allow
    Guard --> Deny: deny
    Guard --> Esc: escalate

    Act --> Terminal: call == terminal_action
    Act --> Clarify: call == request_clarification
    Act --> Invoke: otherwise

    Clarify --> Resume: interrupt(question)
    Resume --> Plan: operator answered<br/>state refreshed

    Invoke --> Observe: ToolRegistry.invoke
    Observe --> Reflect: append observation
    Reflect --> Plan: iter < cap & no repeat fail
    Reflect --> Cap: iter >= cap
    Reflect --> Repeat: same (tool, args) failed N times

    Terminal --> Artifact

    Final --> [*]: final_answer
    Artifact --> [*]: artifact_proposed / draft_proposed
    Deny --> [*]: policy_denied / guardrail_blocked
    Esc --> [*]: requires_execution_approval / requires_command_staging
    Cap --> [*]: iteration_limit
    Repeat --> [*]: repeated_tool_failure
```

Invariants:

- exactly one stop reason per run
- every tool call passes through a policy/guard step first
- terminal artifacts are schema-defined tools, not prompt-parsed blobs
- clarification is durable resume, not a fresh run
- execution-capable tools are not bound in the ordinary loop by default

### 3.1 Per-Iteration Sequence

```mermaid
sequenceDiagram
    autonumber
    actor OP as Operator
    participant L as AgentLoopRuntime
    participant M as Model
    participant P as PolicyEngine
    participant R as ToolRegistry
    participant X as AgentTraceStore

    OP->>L: prompt + state
    L->>X: agent_run_start

    loop until stop_reason
      L->>X: agent_iteration_start
      L->>M: messages + bound tools
      M-->>L: tool_calls | text
      L->>X: agent_plan_update

      alt has tool_calls
        loop each call
          L->>P: evaluate(call, grants, ctx)
          P-->>L: allow | deny | escalate
          alt allow + ordinary tool
            L->>X: agent_tool_start
            L->>R: invoke(call)
            R-->>L: result
            L->>X: agent_tool_result
          else allow + terminal tool
            L->>L: capture artifact
          else allow + request_clarification
            L-->>OP: interrupt(question)
            OP-->>L: answer
          else deny / escalate
            L->>X: agent_guardrail_result
            L-->>OP: stop_reason
          end
        end
        L->>X: agent_iteration_end
      else no tool_calls
        L-->>OP: final_answer
      end
    end

    L->>X: agent_run_end
```

## 4. Stop Reasons

Every run exits with exactly one stop reason.

```mermaid
flowchart LR
    subgraph Success
      FA[final_answer]
      AP[artifact_proposed]
      DP[draft_proposed]
      CC[critique_complete]
      RC[report_complete]
    end
    subgraph Halt
      RQ[requires_clarification]
      RPS[requires_planning_shell]
      RCS[requires_command_staging]
      REA[requires_execution_approval]
      HR[handoff_requested]
    end
    subgraph Limits
      IL[iteration_limit]
      RTF[repeated_tool_failure]
      BE[budget_exceeded]
    end
    subgraph Blocks
      GB[guardrail_blocked]
      PD[policy_denied]
      TU[tool_unavailable]
      TCU[tool_calling_unsupported]
    end
    subgraph Faults
      PE[provider_error]
      CX[cancelled]
    end
```

The runtime contract is that a run chooses one terminal reason, traces it, and
 projects that reason to the caller.

## 5. Task Lifecycle

Future long-horizon task handling should follow this lifecycle:

```mermaid
stateDiagram-v2
    [*] --> requested
    requested --> understood: parse_rover_intent ok
    understood --> clarified: clarification answered<br/>(or not needed)
    clarified --> planned: draft validated
    planned --> draft_approved: draft approval ⏸
    draft_approved --> staged: tier 3
    staged --> execution_approved: live grant ⏸
    execution_approved --> running: executor + monitor active

    running --> paused: operator / monitor pause
    paused --> running: resume
    running --> blocked: policy / obstacle hold
    blocked --> running: condition cleared
    blocked --> failed
    running --> completed: goal reached
    running --> failed: irrecoverable
    running --> cancelled: operator / e-stop
    paused --> cancelled
    blocked --> cancelled

    completed --> reported: reporter wrote episode
    failed --> reported
    cancelled --> reported
    reported --> [*]
```

Hard invariants:

- `running` is only reachable after both draft approval and execution approval
- stopping transitions stay cheap
- every terminal state reaches reporting

## 6. Capability Ladder

```mermaid
flowchart LR
    L0[L0 Chat<br/>compact context only<br/>no tool authority]
    L1[L1 Read-only Agent<br/>tier 0–1 tools]
    L2[L2 Planner Agent<br/>tier 2 tools<br/>DRAFT APPROVAL]
    L3[L3 Staging Agent<br/>tier 3<br/>STAGING APPROVAL]
    L4[L4 Sim Execution<br/>tier 4<br/>SIM CONFIRMATION]
    L5[L5 Live Execution<br/>tier 5<br/>PER-MISSION LIVE GRANT]
    L6[L6 Autonomous Scoped<br/>tier 6<br/>PRE-GRANT + TTL]
    L7[L7 Multi-Robot<br/>fleet scopes]

    L0 --> L1 --> L2
    L2 -.-> L3
    L3 -.-> L4
    L4 -.-> L5
    L5 -.-> L6
    L6 -.-> L7
```

Authority only increases when a new tool tier, policy surface, and approval
surface are added together.

## 7. Future Live Execution With Monitor

The platform is intended to support live execution without letting the model
directly publish commands.

```mermaid
flowchart TB
    OP([operator: run approved inspection])
    G{grant valid?<br/>TTL · scope}
    EXE[executor specialist · tier 5]
    MX[mission_execution<br/>revision · CAS]
    STG[command staging]
    SIM{simulator available?}
    SR[run in simulator]
    DF{operator accepts diff?}
    APH[autopilot handoff]
    HW[rover hardware]

    MON[monitor specialist]
    TEL[(telemetry)]
    PER[(perception)]
    LOCK[(controller lock)]
    BAT[(battery)]

    POL{policy:<br/>geofence · freshness · lock · battery · obstacle}
    PAUSE[executor.pause]
    REPL[planner.replan]
    ESTOP[E-Stop 🔒<br/>synchronous bypass]
    REP[reporter]

    OP --> G
    G -- no --> X1([refuse: requires_execution_approval])
    G -- yes --> EXE --> MX --> STG --> SIM
    SIM -- yes --> SR --> DF
    DF -- no --> X2([rejected at sim diff])
    DF -- yes --> APH
    SIM -- no --> APH
    APH --> HW

    HW --> TEL
    HW --> PER
    HW --> LOCK
    HW --> BAT
    TEL & PER & LOCK & BAT --> MON
    MON --> POL

    POL -- breach .-> ESTOP
    POL -- stale .-> PAUSE
    POL -- replan .-> REPL
    POL -- ok --> HW

    HW -. completed .-> REP
    HW -. failed .-> REP
    PAUSE -. cancelled .-> REP
    ESTOP ===> HW
```

Properties:

- the agent requests through `mission_execution` and staging; it does not
  directly publish commands
- the monitor escalates rather than directly acting
- e-stop remains a synchronous bypass
- all terminal outcomes still reach reporting

## 8. Out Of Scope

Out of scope for this graph document:

- exact runtime dataclass shapes
- exact tool schemas and side-effect declarations
- memory-layer schemas
- event JSON payload shapes
- detailed staging schema and hardware-latency execution specs
