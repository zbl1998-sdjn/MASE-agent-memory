import json
import re
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

# Ensure absolute imports work if the script is run directly
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from mase.model_interface import ModelInterface
from mase_tools.memory.db_core import PROFILE_TEMPLATES, get_connection, upsert_entity_fact

GC_SYSTEM_PROMPT = """You are an asynchronous Memory Garbage Collector (GC) agent.
Your task is to analyze recent conversational memory logs and extract structured facts, project updates, and user preferences.
You MUST output ONLY a valid JSON list of objects. Do not include any conversational text or markdown formatting outside of the JSON block.
Each object must have the following keys:
- "category": must be one of {categories}
- "key": a short, descriptive string for the fact
- "value": the detailed value or status

If there are no new facts to extract, output an empty list: []

Examples of output:
[
  {{"category": "user_preferences", "key": "favorite_food", "value": "pizza"}},
  {{"category": "project_status", "key": "MASE-demo", "value": "implementing Option A for memory GC"}}
]"""

def get_recent_logs(limit: int) -> list[dict[str, Any]]:
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content, timestamp FROM memory_log ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,)
        )
        # Reverse to chronological order
        results = [dict(row) for row in cursor.fetchall()][::-1]
        return results

def run_gc(limit: int = 20):
    logs = get_recent_logs(limit)
    if not logs:
        print("No logs to process.")
        return

    # Format logs for prompt
    log_text = ""
    for log in logs:
        log_text += f"[{log['timestamp']}] {log['role']}: {log['content']}\n"

    prompt = f"Recent memory logs:\n{log_text}\n\nPlease extract facts and output the JSON list."

    model_interface = ModelInterface()

    # Format categories for prompt
    categories = ", ".join([f'"{c}"' for c in PROFILE_TEMPLATES])
    system_prompt = GC_SYSTEM_PROMPT.format(categories=categories)

    messages = [{"role": "user", "content": prompt}]

    print(f"Running GC on last {len(logs)} logs...")
    try:
        response = model_interface.chat(
            agent_type="executor",  # Using generic executor config as the model runner
            messages=messages,
            override_system_prompt=system_prompt,
            mode="default"
        )
    except Exception as e:
        print(f"Error calling LLM: {e}")
        return

    response_content = response.get("message", {}).get("content", "").strip()

    # Parse JSON
    try:
        # Regex to find JSON block if wrapped in markdown
        match = re.search(r"\[.*\]", response_content, re.DOTALL)
        if match:
            json_str = match.group(0)
        else:
            json_str = response_content

        facts = json.loads(json_str)

        if not isinstance(facts, list):
            print("LLM output is not a list. Skipping.")
            return

        for fact in facts:
            category = fact.get("category", "general_facts")
            key = fact.get("key")
            value = fact.get("value")

            if not key or not value:
                continue

            upsert_entity_fact(category, key, str(value))
            print(f"Upserted: [{category}] {key} -> {value}")

        print(f"Successfully processed {len(facts)} facts.")

    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON from LLM: {e}")
        print(f"Raw response:\n{response_content}")

if __name__ == "__main__":
    run_gc()
