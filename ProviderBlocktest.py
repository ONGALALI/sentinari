##ProviderBlocktest.py

print(provider_policy("google"))      # False
print(provider_policy("gemini"))      # False
print(provider_policy("local"))       # True
print(provider_policy("ollama_local"))  # True
print(provider_policy("openai"))      # False