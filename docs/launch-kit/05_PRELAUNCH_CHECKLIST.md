# Pre-Launch Checklist

This is the shortest path from "interesting repo" to "star-worthy launch."

## P0 before major distribution

1. **Add a one-command demo path**
   - Ideal target: `docker-compose up -d`
   - Fallback target: one bootstrap script that pulls models, checks Ollama, and starts a runnable demo

2. **Add a 3-minute proof demo**
   - one memory write
   - one memory-based answer
   - one filesystem screenshot or GIF showing stored JSON / Markdown

3. **Move the benchmark proof above the fold**
   - put the strongest LV-Eval evidence near the top
   - keep the anti-decay wording precise

4. **Add one visual contrast asset**
   - MASE vs vector DB / RAG architecture comparison

5. **Show the white-box evidence**
   - `memory/`
   - `memory/logs/`
   - fact sheet or trace screenshot

## P1 immediately after launch

1. **Ship MCP server**
2. **Ship OpenAI-compatible `/v1/chat/completions`**
3. **Create a short product video or GIF**
4. **Add one "run this benchmark yourself" path**
5. **Add a clear "What MASE is / What MASE is not" section**

## Messaging guardrails

Use:

- "white-box"
- "inspectable"
- "auditable"
- "small-model system design"
- "plain-file memory"

Avoid:

- "AGI memory"
- "vector DBs are dead"
- "fully deterministic answers"
- "state of the art everywhere"

## Launch sequence

1. update README hero and proof block
2. publish launch blog
3. post Show HN
4. post to r/LocalLLaMA
5. post to r/MachineLearning
6. publish X thread with charts and filesystem proof
7. follow with MCP / API roadmap within 24 hours of initial attention

