from config import llm_chat, LLM_PROVIDER

print(f"Testing LLM provider: {LLM_PROVIDER}")
print("Sending test prompt...")

response = llm_chat(
    [{"role": "user", "content": "Say me an really funny joke"}],
    system_prompt="You are a helpful assistant."
)

print(f"Response: {response}")
print("LLM call successful!")
