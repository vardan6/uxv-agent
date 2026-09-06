# Product Vision

*Consolidated 2026-06-20 from the 2026-05-21 vision drafts (the original vision.md and
the chatgpt / claude / claude-v2 / codex companions, now in
[docs/archive/cross-cutting/](../archive/cross-cutting/)). This is the single canonical
vision document.*

---

## Short Vision

Remote Rover is a prototype for a new operating layer between people and robots.

Thanks to these AI agents, humans can now communicate with machines at a much higher
layer of abstraction — describing intent and outcomes rather than dictating low-level
commands — and across richer exchanges that hold context far longer. It increasingly
feels less like operating a tool and more like conversing with a very capable,
human-like collaborator that understands the machine, retains the thread of an
interaction over time, and responds in kind.

For decades, machine interaction has been shaped by the available peripherals:
keyboard, mouse, joystick, touchscreen, dashboards, and specialist control panels.
Those interfaces still matter, especially for direct control and safety. But modern
large language models and AI agents add a new interface class: a human can express a
goal, a question, a correction, or a mission in human language, and software can turn
that intent into structured work over machines, tools, maps, telemetry, and history.

The long-term belief behind this project is that many machines will gain an
**AI-agent layer above their lower-level control systems** — consumer robots, mobile
rovers, drones, industrial machines, humanoid robots, and future robotic systems that
do not yet have stable operator interfaces. The machine still needs sensors,
controllers, safety boundaries, and deterministic execution. The human still needs
authority, visibility, and escalation. AI agents become the layer that helps both
sides communicate at a higher level.

Remote Rover exists to prototype that layer in robotics.

---

## The Shift: A New Human-to-Machine Communication Layer

Every generation of computing is defined less by what machines could do than by how
humans reached them. Punch cards turned intention into holes. The teletype turned it
into typed lines. The keyboard and screen turned it into a conversation of commands.
The mouse and touchscreen turned it into pointing and gesture. Each step compressed
the distance between thought and effect.

The pattern through all of them was the same: **the human had to learn the machine's
language.** Sometimes that language was syntax, sometimes icons, sometimes the shape
of a gesture — but the burden of translation was always on the human side.

That constraint is now reversing. For the first time, a machine can take a sentence —
vague, contextual, half-finished, in any major language — and resolve it into
structured action. Not perfectly, not always, but well enough that designing systems
around this capability is no longer speculative.

The old interaction pattern:

```text
Human
  -> learns the tool interface
  -> manipulates controls
  -> watches raw output
Machine
```

The emerging interaction pattern:

```text
Human intent
  -> AI agent reasoning, tools, context, reporting, approval flow
  -> structured robot mission and supervised execution
Robot systems
```

This is not a claim that language replaces every control. Direct control and safety
interfaces remain. It is a claim that language, agent tools, and generative interfaces
widen the channel between human intention and machine behavior — and that this is a
layer change, not just a better UI. The new periphery is not a new input device; it is
an interpreter that sits between the human and the machine and speaks both fluently.

---

## The Thesis

In the architecture of every machine built from now on, there will be a new layer:

> An AI agent layer that receives human intent, holds context about the machine and
> its world, executes within explicit safety boundaries, monitors what happens, and
> reports back in language a human can act on.

The layer is not the model, and it is not the chat window. It is the interpretive and
supervisory tissue between the human and the actuator — the wheel, the rotor, the
gripper, the camera. It is what lets a person say *"go check whether the back gate is
open and come back if it's blocked"* and have a real machine do something sensible
with that sentence.

Much of what has been hard in robotics for decades — natural mission specification,
on-the-fly replanning, graceful failure, intelligible reporting, supervisory control
of multiple platforms — becomes tractable when this layer is built well. None of it
becomes automatic. The layer has to be designed, and designing it is the work.

---

## Where the Conviction Comes From

The direct motivation came from working with modern AI **coding** agents and noticing
that they can already operate a computer: they read files, run commands, observe
output, change direction, ask for help when stuck, and produce reports a human can
verify. Protocols such as the Model Context Protocol (MCP) extend their reach into
external tools and systems.

Once that lands, a question becomes unavoidable:

> If a modern AI coding agent can manage work on a computer through tools, what happens
> when a robot is exposed to an AI agent through similarly clear interfaces?

A computer has a file system; a robot has terrain. A computer has processes; a robot
has actuators. A computer has logs; a robot has telemetry. The categories map. The
control surfaces differ, but the agent-shaped problem — interpret intent, plan, act,
observe, adjust, report — is the same problem.

The first experiment could have been only an adapter from an agent protocol to a robot
endpoint. The project quickly exposed a stronger requirement: a serious experiment
needs the software layers around the robot, not only a connector. The connective
tissue — a usable, shared substrate for "this is how an agent talks to a rover, an
arm, a drone" — does not yet exist in a widespread form. That gap is the opportunity.

---

## Why Now

This is a practical moment to prototype the layer, because several things only recently
became true at once:

- LLMs can already interpret natural language, generate structured outputs, use tools,
  and report back in language — at a useful level, not just an illustrative one.
- Coding agents demonstrate the pattern: inspect a working environment, operate through
  bounded tools, observe results, and continue from feedback.
- Tool protocols and service boundaries (MCP, tool-use APIs) make it realistic to
  connect agents to external systems rather than keeping them inside chat alone.
- Robotics already provides lower-level patterns to build on: control loops, telemetry,
  mission formats, maps, ground control stations, brokers, simulators, and
  flight-controller boundaries.
- Simulation, ROS 2, and surrounding open robotics tooling are good enough that a small
  team can build the floor under the agent and learn quickly before physical hardware
  cost, safety, and iteration speed dominate the work.

Timing matters for a structural reason: the design decisions made during prototyping
shape the architecture that gets hardened later. The patterns for this layer are not
yet standardized. The teams that answer the hard questions well will define the
vocabulary the industry inherits; teams that wait will implement someone else's.

---

## Why Software First

A real robot is a slow oracle. Every iteration costs hours — charge it, take it
outside, hope the weather and the hardware cooperate, recover when something breaks.
That cadence cannot support the rapid design exploration this layer needs, at least not
at first.

So the entire stack underneath the agent was built in software, with one rule:
**every layer must mirror something a real system actually needs** — not a toy, not a
stub, but a real implementation of a real concern, sized down where necessary and never
faked at the interface. That produced the current shape:

- An **MQTT backbone**, because real robots already use real pub/sub.
- A **telemetry contract**, because real GCSes already define one.
- A **control-frame protocol**, because real autopilots already expect one.
- A **simulator** that drives a physics-correct vehicle with cameras and frame
  publication, because real rovers do.
- A **ground control station** operators actually use to drive and observe, because
  real operations need one.
- **Session replay**, because real incident review requires it.

None of this is the AI layer. All of it is the floor the AI layer needs to stand on:
you cannot meaningfully prototype the supervisor without the things being supervised.
What sits on top of that floor — the LangGraph planning shell, the read-only
deterministic-tool agent, the structured mission drafts, the human-in-the-loop
approvals — those are the actual experiments. The floor exists to make them honest.

---

## What Remote Rover Is Today

The system is built around a working simulator and Ground Control Station:

- **3D Simulator** (`3d-env/`): a Panda3D + Bullet physics rover that publishes
  telemetry and camera frames over MQTT and accepts control input.
- **Ground Control Station** (`gcs_server/`): a FastAPI + browser application operators
  use to monitor, drive, and reason about the rover.

MQTT is the integration backbone between simulator and GCS.

The full operator loop is implemented:

1. A browser connects to the GCS.
2. The operator takes control.
3. The GCS publishes control frames over MQTT.
4. The simulator receives those frames and drives the rover.
5. The simulator publishes telemetry and camera frames back over MQTT.
6. The GCS shows telemetry and video in the browser.

Beyond the live loop, the repository already contains enough working layers to make the
vision concrete:

- MQTT-based control, telemetry, presence signaling, and a bootstrap camera path.
- Session replay / storage and operator-facing settings.
- A shared terrain scene model and map-related context.
- Configurable LLM providers and provider-backed AI chat with persistent sessions.
- A read-only Agent mode with deterministic tools, plus agent traces.
- Structured rover-intent parsing, a mission-draft workflow, route export, and
  mission-execution groundwork.
- A LangGraph-based planning shell with human-in-the-loop approval.
- Compact live context for rover, runtime, settings, map, replay, and mission state.

This matters: the project is not only describing a future. It already has a working
loop where an operator interacts with a simulated robot through the same software
layers an AI-assisted system needs. Current implementation reality lives in the
component design docs rather than in a separate status-hub file.

---

## What This Project Is Prototyping

The main object of study is not only a rover. It is the **human-AI-robot relationship**
around a rover. Remote Rover is a place to develop defensible answers to questions that
don't yet have them:

1. How should a person give a robotic system a mission in natural language — free text,
   structured form, voice with confirmations, or some combination depending on stakes?
2. What exact context should an agent receive directly (map state, telemetry history,
   prior missions, capability descriptors, terrain priors), and what should stay behind
   bounded tools so the model is not exhausted?
3. How should a generated mission become visible, reviewable, and approvable before
   execution?
4. Which decisions belong to deterministic control and policy code rather than the
   model, and where exactly does the agent stop and the operator start?
5. How should an agent monitor telemetry, map state, mission state, sensor evidence,
   and history during operation — and recognize that something is wrong, when "wrong"
   is rarely a clean signal?
6. How should the system report success, uncertainty, failure, or a request for human
   judgment — not a log dump, but something an operator can act on after a long
   autonomous run?
7. How do onboard agents (perception, reflex, local decisions) and offboard agents
   (mission planning, reporting, dialog) divide responsibility without stepping on each
   other — and how does the pattern transfer from a simulated rover to real rovers and
   later to other robot classes?

The project is also a UI and UX prototype: it tests how lower-level dashboards, map
views, replay, direct control, AI chat, agent traces, mission drafts, approvals, and
generated reports should coexist in one operator experience.

---

## Long-Term Target: AI-Assisted Robot Operation

The major long-term direction is AI-assisted and eventually AI-agent-controlled robot
operation. The intended workflow:

1. A user prompts the system by text or voice.
2. AI agents interpret the request using map, telemetry, mission history, and robot
   capability context.
3. The agents generate a structured mission.
4. The mission is passed to an autopilot or controlled execution layer.
5. AI agents monitor mission execution in parallel using telemetry, map state, camera
   images, and later sensors such as lidar, infrared, and ultrasonic.
6. If unexpected obstacles, map mismatches, blocked paths, unsafe state, or
   rule-triggering events appear, the agents decide whether the mission can continue
   within policy.
7. When the decision requires human judgment, the system reports the situation so the
   operator can adjust the prompt, approve a proposed solution, or stop the mission.

Some AI agents may later run **onboard** the robot for low-latency perception or local
decisions. Others run **outside** the robot in the GCS or backend services for mission
planning, map reasoning, reporting, and human interaction. Near-term work focuses on
the outside agents: prompt handling, mission generation, map context, and supervised
decision flow.

This target is implemented step by step. The current AI direction is the shared agent
runtime described in the canonical AI agent docs: keep always-on context compact,
expose larger data surfaces through bounded tools, preserve a two-approval model, make
every agent run visible and traceable, and keep all execution authority outside the
model until a separate safety design unlocks later capability tiers.

---

## Design Position

The vision should be ambitious, but the implementation stance stays disciplined.

- **Human language at the top.** Humans express high-level goals and receive high-level
  explanations. The system reduces the translation burden between intent and technical
  operation.
- **Structured systems underneath.** Robots do not run on vague language. Agent output
  must become structured missions, bounded tool calls, policy decisions, controller
  handoffs, telemetry interpretation, and traceable state transitions.
- **Human authority where it matters.** Planning approval and execution approval are
  separate concerns. Explicit human-in-the-loop points stay wherever safety,
  uncertainty, or operational responsibility require them.
- **Simulation before hardware pressure.** The software model is not a detour. It is the
  fast path for learning the architecture, protocols, UX, and agent boundaries that
  should survive later hardware integration.
- **Prototype before hardening.** Remote Rover is intentionally refactorable. Several
  design improvements have already surfaced through implementation and a substantial
  documentation refactoring effort. That cycle is the work, not an interruption to it —
  a prototype that doesn't generate refactoring pressure isn't being pushed hard enough.

---

## Scope Beyond Rovers

The current rover is a concrete testbed, not the final limit. Read the same architecture
against:

- A vacuum robot you can describe rooms to in plain language, which explains what it
  skipped and why.
- A humanoid platform that takes mission-level direction instead of teleoperation.
- A delivery quadcopter that handles route-exception decisions inside policy and reports
  the ones it cannot.
- A small fleet of inspection drones supervised by one human through summaries, not
  joysticks.
- An aircraft autopilot extended with an agent that mediates between pilot intent and
  system state.
- Industrial and warehouse robots with different safety envelopes and lower-level
  controls.

Each has different kinematics, regulation, safety envelope, and hardware, but the same
higher-level pressure: humans state goals and constraints, machines expose state and
capability, and software must translate, supervise, explain, and escalate. A team that
learns to build this layer well for one platform learns most of the work needed for the
others. Remote Rover focuses on robotics because robotics makes the boundary visible:
intent becomes motion in the physical world, and mistakes cannot be hidden behind a
pleasant chat response.

---

## Honest Maturity Statement

Remote Rover should be understood as a working integrated prototype and a learning
platform for the next human-machine interface layer. It is:

- a working simulator and control platform,
- a practical integration baseline,
- a strong demonstration and development environment,
- a staging point for future hardening, better media transport, authentication, and
  multi-instance state management.

It is **not** yet a production robot operations stack. It is not a finished GCS or a
hardened agent runtime. The current simulator path, bootstrap media transport, AI
workflow migration, and future hardware handoff all still have work ahead. The
documentation and architecture have already been refactored and will evolve again as
stronger patterns appear. That is part of the value: it creates a place to prototype the
agent layer with enough real system structure that the lessons transfer.

---

## Use Cases This Project Is Useful For

- Simulator-first control workflow development.
- Operator dashboard and control UX development.
- Validating MQTT-based system contracts before connecting to a real rover.
- Presenting a future architecture for remote supervision, video, telemetry, operator
  control, and AI-agent-assisted autonomy.
- A learning path for LangChain, LangGraph, RAG, and agentic systems applied to a
  concrete robotics scenario.

---

## Presentation Aids

### Presentation message

> The future robot interface is not only a better dashboard. It is an AI-agent layer
> that accepts human intent, operates over structured robot systems, keeps humans in
> control of critical decisions, and reports back in human terms.
>
> Remote Rover is the prototype environment for learning how to build that layer.

### Suggested demo opening

1. Robots already have sensors, controllers, telemetry, and operator tools.
2. Modern AI adds a new high-level interface: natural-language intent plus tool-using
   agents.
3. The missing work is the layer between them: context, missions, approvals, monitoring,
   reporting, and safe handoff.
4. Remote Rover prototypes that layer using a simulated rover, a Ground Control Station,
   MQTT contracts, maps, replay, and an evolving AI agent workflow.
5. The demo then shows the current system from direct operator control toward
   AI-assisted robot operation.

### One-slide version

**Remote Rover prototypes the AI-agent layer between humans and robots.**

- Human side: intent, questions, approvals, supervision, reports.
- Agent layer: language understanding, tools, maps, telemetry context, mission
  drafting, monitoring.
- Robot side: simulators now, real controllers and hardware later.
- Goal: learn the UX and architecture for AI-assisted robotic operation before it
  becomes the default expectation.

### In one paragraph

For most of computing history, the interface between humans and machines was a device
the human learned to use. That era is closing. The new interface is an AI agent that
interprets human language, supervises machine execution, monitors what happens in the
world, and reports back in terms a human can act on. Robotics absorbs this layer first
and most visibly, because robots have always been bottlenecked by the difficulty of
telling them what to do. Remote Rover is a place to figure out, at small scale and in
honest detail, how that layer should be built. The hardware will come; the work right
now is the layer.

---

## Recommended Reading

For a general or product-focused audience:

1. [GCS Requirements](../components/gcs/requirements.md) — operator workflow and UI
   expectations.
2. [AI Agent Requirements](../components/ai-agent/requirements.md) — AI behavior,
   safety, and mission workflow.
3. [Simulator Requirements](../components/simulator/requirements.md) — current
   simulator baseline and future simulator constraints.
4. [AI Agent Design](../components/ai-agent/design.md) — current implementation
   direction.

For technical readers:

1. [Architecture](./architecture.md)
2. [GCS Design](../components/gcs/design.md)
3. [AI Agent Design](../components/ai-agent/design.md)
4. [Simulator Design](../components/simulator/design.md)
5. [Run And Config Guide](./operations/run-and-config.md)
