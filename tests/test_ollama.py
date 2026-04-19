import ollama

response = ollama.chat(
    model="qwen2.5:3b",
    messages=[{"role": "user", "content": "你好，请用一句话介绍你自己。"}],
)
print(response["message"]["content"])
