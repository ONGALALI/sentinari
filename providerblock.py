#provider.py

def provider_policy(provider: str) -> bool:
    p = (provider or "").strip().lower().replace("-", "_")
    blocked = {
        "google", "gemini", "vertex", "vertex_ai", "google_cloud",
        "openai", "microsoft", "copilot", "azure", "github_models",
        "gcp", "ai_studio"
    }
    allowed = {"local", "local_runtime", "sentinari", "ollama_local"}
    if p in blocked:
        return False
    if p in allowed:
        return True
    return False