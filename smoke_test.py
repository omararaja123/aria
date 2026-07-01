"""LangSmith configuration smoke test.

Loads .env, normalizes LANGSMITH_* / LANGCHAIN_* compatibility variables, and
writes a tiny test run. Some LangSmith keys can write traces but cannot read or
list projects, so this avoids project-read APIs that may return 403.
"""

from dotenv import load_dotenv
import requests
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aria.langsmith_config import (
    get_api_key,
    get_endpoint,
    get_langsmith_client,
    get_project_name,
    get_workspace_id,
    setup_langsmith,
)


@traceable(name="ARIA LangSmith Smoke Test", tags=["aria", "smoke-test"])
def _smoke_trace() -> str:
    run_tree = get_current_run_tree()
    if run_tree:
        print(f"trace_id={run_tree.trace_id}")
    return "ok"


def _redact(value: str) -> str:
    if not value:
        return "not set"
    if len(value) <= 10:
        return "***"
    return f"{value[:8]}...{value[-4:]}"


def main() -> None:
    load_dotenv()

    configured = setup_langsmith()
    print(f"tracing_configured={configured}")
    print(f"endpoint={get_endpoint()}")
    print(f"project={get_project_name()}")
    print(f"workspace_id={_redact(get_workspace_id())}")
    print(f"api_key={_redact(get_api_key())}")

    client = get_langsmith_client()
    if not client:
        print("LangSmith client was not created.")
        return

    headers = {"x-api-key": get_api_key()}
    if get_workspace_id():
        headers["X-Tenant-Id"] = get_workspace_id()
    permission_probe = requests.post(
        f"{get_endpoint()}/runs",
        headers=headers,
        json={},
        timeout=10,
    )
    if permission_probe.status_code == 403:
        workspace_hint = (
            " A workspace ID is currently configured; if you are using a "
            "Developer Free personal access token, comment out "
            "LANGSMITH_WORKSPACE_ID and try again."
            if get_workspace_id()
            else " If you are using Developer Free, create a fresh Personal Access "
            "Token in the same account you use to open LangSmith."
        )
        raise SystemExit(
            "LangSmith rejected trace writes with 403 Forbidden. "
            "Create a new LangSmith API key with trace write access for this "
            "workspace, or update LANGSMITH_WORKSPACE_ID to the workspace that "
            f"owns this key.{workspace_hint}"
        )

    result = _smoke_trace(
        langsmith_extra={"project_name": get_project_name(), "client": client}
    )
    client.flush()
    print(f"Success: queued and flushed smoke trace result={result!r}.")


if __name__ == "__main__":
    main()
