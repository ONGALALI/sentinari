import os
import yaml
from pathlib import Path

def get_settings():
    """
    Loads settings from the settings.yaml file.
    Provides a unified configuration interface for the Sentinari app.
    """
    # Check for environment variable override first
    env_config = os.environ.get("SENTINARI_CONFIG_PATH") or os.environ.get("SMI_CONFIG_PATH")
    if env_config:
        config_path = Path(env_config).resolve()
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)

    # Resolve the path to settings.yaml relative to the project root
    project_root = Path(__file__).parent.parent.resolve()
    config_path = project_root / "config" / "settings.yaml"
    
    if not config_path.exists():
        # Try a fallback path if the first one fails
        config_path = Path(os.getcwd()) / "config" / "settings.yaml"
        
    if not config_path.exists():
        raise FileNotFoundError(f"Critical Error: Could not find settings.yaml at {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

if __name__ == "__main__":
    try:
        settings = get_settings()
        print("Successfully loaded settings!")
        print(f"Model: {settings['llm']['chat_model']}")
    except Exception as e:
        print(f"Error loading settings: {e}")
