# LLM Provider Agentic Capability Matrix (Configured in This GCS)

Last reviewed: 2026-05-10  
Config source reviewed: `../config/common.local.json` (16 provider entries)

This matrix is based on:
- Your currently configured providers/models in this GCS instance.
- Vendor/provider docs for tool/function-calling and context limits.
- Current GCS runtime behavior in Agent mode (tool support inference + fallback warning).

## How GCS currently decides “agent-capable”

In Agent mode, UI/runtime currently treats a provider as tool-capable when either:
- provider capabilities include `tool_calling` or `planner`, or
- provider type is not `ollama` (fallback heuristic in UI).

Reference: [static/ai.js](/mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server/static/ai.js)

## Matrix

| Provider (Configured Display Name)  | Provider Type       | Model ID                      | Enabled | Configured Capabilities       | Tool/Function Calling (Docs)                                                    | Context Window (Docs)                        | Agentic Fit Note                                                                  |
| ----------------------------------- | ------------------- | ----------------------------- | ------: | ----------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------- |
| NVIDIA NIM z-ai/glm4.7              | `nvidia_nim`        | `z-ai/glm4.7`                 |       ✅ | `chat, planner, tool_calling` | ✅ NVIDIA NIM page explicitly mentions tool use / tool-call parser for GLM-4.7   | 131,072                                      | Strong fit for tool-heavy agent loops.                                            |
| OpenRouter Claude Sonnet Example    | `openrouter`        | `anthropic/claude-sonnet-4.5` |       ❌ | `chat, reasoning`             | ✅ OpenRouter supports tool calling; Anthropic Sonnet 4.5 supports tool use      | 200K (Anthropic API baseline for Sonnet 4.5) | Good for planning/reasoning agents; disabled currently.                           |
| OpenAI GPT Example                  | `openai`            | `gpt-5.2`                     |       ✅ | `chat, reasoning`             | ✅ OpenAI function calling/tool calling supported                                | 400,000 (model compare page)                 | Very strong general agent model.                                                  |
| Anthropic Claude Sonnet Example     | `anthropic`         | `claude-sonnet-4-5`           |       ❌ | `chat, reasoning`             | ✅ Anthropic tool use supported                                                  | 200K                                         | Strong tool-using reasoning model; disabled currently.                            |
| Google Gemini Flash Example         | `google_gemini`     | `gemini-2.5-flash`            |       ❌ | `chat, vision`                | ✅ Gemini function calling docs include `gemini-2.5-flash` examples              | 1M (Gemini 2.5 model card)                   | Good for multimodal + tools; disabled currently.                                  |
| Ollama Local Llama Example          | `ollama`            | `glm-4.7:cloud`               |       ✅ | `chat, tool_calling`          | ✅ Verified: Ollama docs support tool calling, model page is tagged `tools`, and this GCS host returned a real `tool_calls` response on 2026-05-10 | Ollama page lists 198K context on the library entry | Good agent candidate when you want the Ollama cloud route.                        |
| LM Studio Local Example             | `lm_studio`         | `local-model`                 |       ❌ | `chat`                        | ⚠️ LM Studio API supports OpenAI-style tools if model/template supports it      | Model-dependent                              | Placeholder model ID; no capability claim possible until concrete model selected. |
| Mistral Large Example               | `mistral`           | `mistral-large-latest`        |       ❌ | `chat, reasoning`             | ✅ Mistral function calling docs show `mistral-large-latest` tool usage          | 131,072                                      | Good enterprise agent candidate; disabled currently.                              |
| Cohere Command A Example            | `cohere`            | `command-a-03-2025`           |       ❌ | `chat, embeddings`            | ✅ Cohere Command A reasoning docs describe tool use/agent workflows             | 256,000                                      | Strong RAG + tool-use option; disabled currently.                                 |
| Hugging Face Router GPT OSS Example | `huggingface`       | `openai/gpt-oss-120b`         |       ❌ | `chat, reasoning`             | ✅ HF Inference Providers support function calling via OpenAI-compatible router  | 131,072 (model family docs)                  | Strong self-host/flexible option; disabled currently.                             |
| OpenAI GPT gpt-4.1                  | `openai`            | `gpt-4.1`                     |       ✅ | `chat, reasoning`             | ✅ Function calling + tool support listed on model page                          | 1,047,576                                    | Strong long-context non-reasoning agent baseline.                                 |
| Ollama Local llama3:8b              | `ollama`            | `llama3:8b`                   |       ✅ | `chat`                        | ⚠️ Ollama supports tools; this model line is not guaranteed for robust tool use | 8K (Ollama library page)                     | Good lightweight chat; weak for complex tool-agent tasks due to short context.    |
| Ollama Local gemma4:e4b             | `ollama`            | `gemma4:e4b`                  |       ✅ | `chat`                        | ⚠️ Ollama supports tools; Gemma 4 family advertises function-calling support    | 128K (Gemma 4 small models)                  | Promising local agent option; validate call accuracy with your tool schemas.      |
| Together GPT OSS Example            | `together`          | `openai/gpt-oss-20b`          |       ❌ | `chat, reasoning`             | ✅ Together function-calling docs list GPT-OSS models as supported               | 131,072 (OpenAI model page for gpt-oss-20b)  | Cost/perf-friendly agent candidate; disabled currently.                           |
| Custom OpenAI-compatible Example    | `openai_compatible` | `custom-model-id`             |       ❌ | `chat`                        | ❓ Depends entirely on upstream vendor/model                                     | Unknown                                      | Placeholder; cannot rank until real model + docs are specified.                   |
| Ollama Local gemma4:e2b             | `ollama`            | `gemma4:e2b`                  |       ✅ | `chat`                        | ⚠️ Ollama supports tools; Gemma 4 family advertises function-calling support    | 128K (Gemma 4 small models)                  | Best low-footprint local candidate among your enabled Ollama entries.             |

## Practical recommendations for your current setup

1. Primary agent providers (today): `gpt-5.2`, `gpt-4.1`, `z-ai/glm4.7` (all enabled and tool-capable by docs).
2. Keep most Ollama models behind a tool-call conformance test, but treat `glm-4.7:cloud` as validated in this environment.
3. For placeholder IDs (`local-model`, `custom-model-id`), treat tool support as unknown until replaced with concrete model IDs.
4. Update provider `capabilities` metadata to include `tool_calling` explicitly for entries you have validated.

## Sources

- OpenAI GPT-4.1 model page: https://platform.openai.com/docs/models/gpt-4.1
- OpenAI model compare (GPT-5.2 context/features): https://platform.openai.com/docs/models/compare
- OpenAI gpt-oss-20b model page: https://platform.openai.com/docs/models/gpt-oss-20b
- OpenAI gpt-oss-120b model page: https://platform.openai.com/docs/models/gpt-oss-120b
- OpenAI function calling guide: https://platform.openai.com/docs/guides/function-calling
- Anthropic tool use overview: https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
- Anthropic context windows: https://platform.claude.com/docs/en/build-with-claude/context-windows
- Google Gemini function calling: https://ai.google.dev/gemini-api/docs/function-calling
- Google Gemini models index: https://ai.google.dev/gemini-api/docs/models
- Gemini 2.5 Flash model card PDF: https://modelcards.withgoogle.com/assets/documents/gemini-2.5-flash.pdf
- NVIDIA NIM GLM-4.7 reference: https://docs.api.nvidia.com/nim/reference/z-ai-glm4-7
- Mistral function calling: https://docs.mistral.ai/studio-api/conversations/function-calling
- Mistral known limitations (context): https://docs.mistral.ai/resources/known-limitations
- Cohere Command A Reasoning: https://docs.cohere.com/docs/command-a-reasoning
- Together function calling overview: https://docs.together.ai/docs/inference/function-calling/overview
- Groq tool use overview: https://console.groq.com/docs/tool-use/overview
- Hugging Face function calling (Inference Providers): https://huggingface.co/docs/inference-providers/en/guides/function-calling
- Ollama tool calling: https://docs.ollama.com/capabilities/tool-calling
- Ollama Llama 3 library page: https://ollama.com/library/llama3
- Ollama Gemma 4 page (context/function-calling notes): https://ollama.com/library/gemma4:e2b-mlx-bf16
- OpenRouter tool calling docs: https://openrouter.ai/docs/docs/features/tool-calling
