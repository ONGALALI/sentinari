@coder_agent.register_for_llm(name="scan_workspace", description="Returns file names inside the project folder structure.")
@user_proxy.register_for_execution(name="scan_workspace")
def scan_workspace() -> list:
    return [os.path.join(r, f) for r, d, fs in os.walk(workspace_path) for f in fs]
