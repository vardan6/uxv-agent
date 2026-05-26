# Product Vision

## What Remote Rover Is

Remote Rover is a foundation for a remote robot operations stack. The current prototype focuses on a simulated rover because it is the fastest safe path for validating control, telemetry, maps, replay, and operator workflows. The longer-term goal is to support real rovers and other robot types through the same operating model.

The system is built around two working applications and one separate simulator experiment:

- **3D Simulator** (`3d-env/`): a Panda3D + Bullet physics rover that publishes telemetry and camera frames over MQTT and accepts control input
- **Ground Control Station** (`gcs_server/`): a FastAPI + browser application operators use to monitor, drive, and reason about the rover
- **rover-sim-next** (`rover-sim-next/`): scaffolded ROS 2 + Gazebo simulator path in the repository, not part of the working runtime today

MQTT is the integration backbone between simulator and GCS.

## What The Project Demonstrates Today

The full operator loop is implemented:

1. A browser connects to the GCS
2. The operator takes control
3. The GCS publishes control frames over MQTT
4. The simulator receives those frames and drives the rover
5. The simulator publishes telemetry and camera frames back over MQTT
6. The GCS shows telemetry and video in the browser

Beyond the live loop, the system has session replay, configurable LLM providers, an AI Chat workspace with persistent sessions, a read-only Agent mode with deterministic tools, structured rover-intent parsing, mission-draft workflow, and a LangGraph-based planning shell with human-in-the-loop approval. Current implementation reality lives in the component design docs rather than in a separate status-hub file.

## Long-Term Target: AI-Assisted Robot Operation

The major long-term direction is AI-assisted and eventually AI-agent-controlled robot operation. The intended workflow:

1. A user prompts the system by text or voice
2. Outside-GCS AI agents interpret the request using map, telemetry, mission history, and robot capability context
3. The agents generate a structured mission
4. The mission is passed to an autopilot or controlled execution layer
5. AI agents monitor mission execution in parallel using telemetry, map state, camera images, and later sensors such as lidar, infrared, and ultrasonic
6. If unexpected obstacles, map mismatches, blocked paths, unsafe state, or rule-triggering events appear, the agents decide whether the mission can continue within policy
7. When the decision requires human judgment, the system reports the situation so the operator can adjust the prompt, approve a proposed solution, or stop the mission

Some AI agents may later run onboard the robot for low-latency perception or local decisions. Others run outside the robot in the GCS or backend services for mission planning, map reasoning, reporting, and human interaction. Near-term work focuses on the outside agents: prompt handling, mission generation, map context, and supervised decision flow.

This target is implemented step by step. The current AI direction is the shared agent runtime described in the canonical AI agent docs: keep always-on context compact, expose larger data surfaces through bounded tools, preserve a two-approval model, make every agent run visible and traceable, and keep all execution authority outside the model until a separate safety design unlocks later capability tiers.

## Current Position

The project is not yet in a final production architecture. It should be understood as:

- a working simulator and control platform
- a practical integration baseline
- a strong demonstration and development environment
- a staging point for future hardening, better media transport, authentication, and multi-instance state management

## Use Cases This Project Is Useful For

- simulator-first control workflow development
- operator dashboard and control UX development
- validating MQTT-based system contracts before connecting to a real rover
- presenting a future architecture for remote supervision, video, telemetry, operator control, and AI-agent-assisted autonomy
- learning path for LangChain, LangGraph, RAG, and agentic systems applied to a concrete robotics scenario

## Recommended Reading

For a general or product-focused audience:

1. [GCS Requirements](../components/gcs/requirements.md) — operator workflow and UI expectations
2. [AI Agent Requirements](../components/ai-agent/requirements.md) — AI behavior, safety, and mission workflow
3. [Simulator Requirements](../components/simulator/requirements.md) — current simulator baseline and future simulator constraints
4. [AI Agent Design](../components/ai-agent/design.md) — current implementation direction

For technical readers:

1. [Architecture](./architecture.md)
2. [GCS Design](../components/gcs/design.md)
3. [AI Agent Design](../components/ai-agent/design.md)
4. [AI Agent Graph Spec](../components/ai-agent/internals/graph-spec.md)
5. [Simulator Design](../components/simulator/design.md)
6. [Run And Config Guide](./operations/run-and-config.md)
