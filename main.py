
"""
ARIA Main Entry Point — Step 13 Complete

Complete LangGraph StateGraph with all nodes:
Supervisor → Subagent Dispatcher → Validator → Deduplicator → Ranker →
Summarizer → Drafter → Human Review (interrupt) → Publisher

Uses SqliteSaver for persistent state checkpointing across the human review pause.
Streams execution with rich terminal output and progress reporting.
"""

import json
import logging
import os
import subprocess
import sys
import time
import uuid
import webbrowser
from datetime import datetime
from typing import Any

from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver
from rich.console import Console
from rich.logging import RichHandler

from config import INTEREST_PROFILE
from memory.db import init_db
from state import ARIAState

# Import all nodes
from agents.supervisor import supervisor_node
from agents.subagent_dispatcher import subagent_dispatcher_node
from tools.validator import validator_node
from tools.deduplicator import deduplicator_node
from tools.ranker import ranker_node
from tools.summarizer import summarizer_node
from tools.drafter import drafter_node
from tools.human_review import human_review_node
from tools.publisher import publisher_node

# Setup console and logging
console = Console()

# Configure logging with rich handler
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, rich_tracebacks=True)]
)
logger = logging.getLogger(__name__)


def launch_streamlit_review(run_id: str, console: Console) -> subprocess.Popen:
    """
    Launch Streamlit review UI in background.
    Returns the process handle so we can monitor it.
    """
    console.print("[bold cyan]🌐 Launching Streamlit review interface...[/bold cyan]\n")

    env = os.environ.copy()
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_SERVER_PORT"] = "8501"
    env["STREAMLIT_LOGGER_LEVEL"] = "error"

    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "ui/review_app.py",
         "--logger.level=error", "--client.showErrorDetails=true"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        env=env,
    )

    time.sleep(4)

    if process.poll() is not None:
        stdout, stderr = process.communicate()
        console.print("[red]✗ Streamlit failed to start[/red]")
        console.print("[red]Error output:[/red]")
        if stderr:
            console.print(f"[red]{stderr}[/red]")
        if stdout:
            console.print(f"[red]{stdout}[/red]")
        raise RuntimeError("Streamlit failed to start. Check error output above.")

    console.print("[green]✓ Streamlit started at http://localhost:8501[/green]\n")
    console.print("[cyan]Opening in your browser...[/cyan]\n")

    try:
        webbrowser.open("http://localhost:8501")
    except Exception:
        pass

    return process


def wait_for_review_decision(graph, config: dict, console: Console, max_wait_seconds: int = 3600) -> dict:
    """
    Poll for user decision from Streamlit (written to .aria_review_decision.json).
    Once decision is detected, return the decision for graph resume.
    """
    import json
    import os

    console.print("[cyan]Waiting for your review decision...[/cyan]\n")
    console.print("[dim]You can:[/dim]")
    console.print("  [green]✅ Approve & Send[/green] — publish newsletter")
    console.print("  [yellow]🔄 Re-run[/yellow] — adjust and re-rank")
    console.print("  [red]❌ Reject[/red] — start fresh from supervisor\n")

    start_time = time.time()
    poll_interval = 1  # Check every 1 second

    while time.time() - start_time < max_wait_seconds:
        try:
            # Check if decision file exists
            if os.path.exists(".aria_review_decision.json"):
                with open(".aria_review_decision.json", "r") as f:
                    decision_data = json.load(f)

                # Report decision
                if decision_data.get("review_approved"):
                    console.print("[bold green]✓ Decision received: APPROVED[/bold green]\n")
                elif decision_data.get("review_rejected"):
                    console.print("[bold yellow]⟳ Decision received: REJECT & RESTART[/bold yellow]\n")
                elif decision_data.get("review_re_rank"):
                    console.print("[bold cyan]⟳ Decision received: RE-RANK[/bold cyan]\n")

                # Clean up decision file
                try:
                    os.remove(".aria_review_decision.json")
                except Exception:
                    pass

                return decision_data

            # No decision yet, wait and retry
            time.sleep(poll_interval)

        except Exception as e:
            logger.debug(f"Poll error (will retry): {e}")
            time.sleep(poll_interval)

    # Timeout - default to approve
    console.print("[yellow]⚠️  Review timeout (>1 hour). Defaulting to APPROVE.[/yellow]\n")
    return {"review_approved": True, "review_rejected": False, "review_re_rank": False, "human_review_edits": []}


def resume_from_checkpoint(graph, config: dict, decision_state: dict, console: Console) -> tuple[dict, bool]:
    """
    Resume graph execution with user decision by manually calling remaining nodes.
    Returns (final_state, hit_human_review_again).
    If hit_human_review_again is True, the UI should be refreshed.
    """
    console.print("[bold cyan]Resuming pipeline from checkpoint...[/bold cyan]\n")
    console.print("━" * 70)

    final_state = None
    hit_human_review_interrupt = False

    # Get current checkpoint state and merge with decision
    try:
        current_snapshot = graph.get_state(config)
        if current_snapshot and current_snapshot.values:
            # Merge decision into current state
            merged_state = current_snapshot.values.copy()
            merged_state.update(decision_state)
        else:
            merged_state = decision_state
    except Exception as e:
        logger.debug(f"Could not get current state: {e}, using decision state")
        merged_state = decision_state

    try:
        # First, run human_review to process decision
        reviewed_state = human_review_node(merged_state)

        # Determine routing path
        if reviewed_state.get("review_approved"):
            # Route to publisher
            console.print(f"\n[bold blue]→ {'human_review':25}[/bold blue]", end="")
            console.print(f"  {len(reviewed_state.get('articles', [])):3d} articles  ", style="cyan")

            console.print(f"\n[bold blue]→ {'publisher':25}[/bold blue]", end="")
            final_state = publisher_node(reviewed_state)
            article_count = len(final_state.get("articles", []))
            llm_calls = final_state.get("llm_call_count", 0)
            cost = final_state.get("estimated_cost_usd", 0.0)
            console.print(
                f"  {article_count:3d} articles  "
                f"{llm_calls:2d} LLM calls  "
                f"${cost:6.3f}",
                style="cyan"
            )

        elif reviewed_state.get("review_rejected"):
            # Full re-run from supervisor
            console.print("\n[bold yellow]Re-running from supervisor...[/bold yellow]")
            # Reset state for full re-run
            reviewed_state["articles"] = []
            reviewed_state["fetch_errors"] = []
            reviewed_state["llm_call_count"] = 0
            reviewed_state["estimated_cost_usd"] = 0.0
            reviewed_state["re_run_count"] = reviewed_state.get("re_run_count", 0) + 1
            # Continue streaming from supervisor
            for event in graph.stream(reviewed_state, config=config, stream_mode="updates"):
                for node_name, node_state in event.items():
                    if isinstance(node_state, dict):
                        final_state = node_state

            # Check if we hit human_review interrupt again
            try:
                state_snapshot = graph.get_state(config)
                if state_snapshot and state_snapshot.next and "human_review" in state_snapshot.next:
                    hit_human_review_interrupt = True
            except Exception:
                pass

        elif reviewed_state.get("review_re_rank"):
            # Re-rank with adjusted profile
            console.print("\n[bold cyan]Re-ranking with adjusted profile...[/bold cyan]")
            reviewed_state["re_run_count"] = reviewed_state.get("re_run_count", 0) + 1
            # Continue streaming from ranker
            for event in graph.stream(reviewed_state, config=config, stream_mode="updates"):
                for node_name, node_state in event.items():
                    if isinstance(node_state, dict):
                        final_state = node_state

            # Check if we hit human_review interrupt again
            try:
                state_snapshot = graph.get_state(config)
                if state_snapshot and state_snapshot.next and "human_review" in state_snapshot.next:
                    hit_human_review_interrupt = True
            except Exception:
                pass

        else:
            # Default to publisher
            final_state = publisher_node(reviewed_state)

    except Exception as e:
        logger.error(f"Error during resume: {e}")
        final_state = merged_state

    console.print("\n" + "━" * 70)
    return final_state, hit_human_review_interrupt


def build_graph() -> StateGraph:
    """Build the complete ARIA LangGraph with all 9 nodes in correct order."""
    graph = StateGraph(ARIAState)

    # Add all nodes in pipeline order
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("subagent_dispatcher", subagent_dispatcher_node)
    graph.add_node("validator", validator_node)
    graph.add_node("deduplicator", deduplicator_node)
    graph.add_node("ranker", ranker_node)
    graph.add_node("summarizer", summarizer_node)
    graph.add_node("drafter", drafter_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("publisher", publisher_node)

    # Wire edges in pipeline order
    graph.add_edge("__start__", "supervisor")
    graph.add_edge("supervisor", "subagent_dispatcher")
    graph.add_edge("subagent_dispatcher", "validator")
    graph.add_edge("validator", "deduplicator")
    graph.add_edge("deduplicator", "ranker")
    graph.add_edge("ranker", "summarizer")
    graph.add_edge("summarizer", "drafter")
    graph.add_edge("drafter", "human_review")

    # Conditional routing from human review checkpoint
    def route_after_review(state):
        """Route based on human decision from review checkpoint."""
        if state.get("review_approved"):
            return "publisher"
        elif state.get("review_rejected"):
            return "supervisor"  # Full re-run from supervisor
        elif state.get("review_re_rank"):
            return "ranker"  # Re-rank with adjusted profile
        else:
            return "publisher"  # Default: publish as-is

    graph.add_conditional_edges(
        "human_review",
        route_after_review,
        {"publisher": "publisher", "supervisor": "supervisor", "ranker": "ranker"},
    )
    graph.add_edge("publisher", "__end__")

    logger.info("Graph built successfully with 9 nodes")
    return graph


def main():
    """Execute the complete ARIA pipeline from start to human review pause."""
    start_time = datetime.now()

    console.print("\n[bold cyan]🚀 ARIA Newsletter Pipeline — Step 13 Complete[/bold cyan]")
    console.print("[dim]Complete LangGraph with 9 nodes, checkpoint, and human-in-loop[/dim]\n")

    try:
        # Load .env variables
        from dotenv import load_dotenv
        load_dotenv()
        logger.info("Environment variables loaded from .env")

        # Initialize database
        console.print("[yellow]Initializing database...[/yellow]")
        init_db()
        logger.info("Database initialized")
        console.print("[green]✓ Database initialized (8 tables ready)[/green]\n")

        # Build and compile graph
        console.print("[yellow]Building LangGraph (9 nodes)...[/yellow]")
        graph_builder = build_graph()

        console.print("[yellow]Compiling with MemorySaver checkpointer...[/yellow]")
        checkpointer = MemorySaver()
        graph = graph_builder.compile(
            checkpointer=checkpointer,
            interrupt_before=["human_review"],  # Pause before human review for approval
        )
        logger.info("Graph compiled with interrupt_before=['human_review']")
        console.print("[green]✓ Graph compiled with interrupt at human_review[/green]\n")

        # Create initial state
        run_id = str(uuid.uuid4())
        initial_state: ARIAState = {
            "run_id": run_id,
            "run_timestamp": start_time,
            "user_id": "aria_user",
            "interest_profile": INTEREST_PROFILE,
            "interest_profile_edits": None,
            "articles": [],
            "fetch_errors": [],
            "total_fetched": 0,
            "validation_stats": {},
            "dedup_stats": {},
            "ranking_stats": {},
            "human_review_edits": [],
            "review_approved": False,
            "review_rejected": False,
            "review_re_rank": False,
            "re_run_count": 0,
            "llm_call_count": 0,
            "estimated_cost_usd": 0.0,
            "elapsed_seconds": 0.0,
            "published": False,
            "fetch_plan": "",
            "priority_topics": [],
            "subagent_instructions": {},
            "estimated_budget_remaining": 2.0,
            "draft_newsletter": "",
            "newsletter_metadata": {},
            "last_newsletter_date": None,
            "topic_history": {},
            "blacklisted_sources": [],
            "filtered_article_ids": [],
            "message_id": None,
            "publish_timestamp": None,
            "publish_status": None,
            "review_notes": None,
            "review_timestamp": None,
        }

        console.print(f"[cyan]Run ID:[/cyan] {run_id}")
        console.print(f"[cyan]Interests:[/cyan] {len(initial_state['interest_profile'])} weighted topics")
        console.print(f"[cyan]Budget:[/cyan] ${initial_state['estimated_budget_remaining']:.2f}\n")

        # Stream execution
        console.print("[bold yellow]Executing pipeline (9 nodes)...[/bold yellow]\n")
        console.print("━" * 70)

        config = {"configurable": {"thread_id": run_id}}
        node_metrics = {}
        final_state = None

        for event in graph.stream(initial_state, config=config, stream_mode="updates"):
            for node_name, node_state in event.items():
                # Handle different event types (dict vs tuple)
                if isinstance(node_state, dict):
                    final_state = node_state
                    article_count = len(node_state.get("articles", []))
                    llm_calls = node_state.get("llm_call_count", 0)
                    cost = node_state.get("estimated_cost_usd", 0.0)
                else:
                    # Skip non-dict events (e.g., interrupt notifications)
                    continue

                console.print(f"\n[bold blue]→ {node_name:25}[/bold blue]", end="")
                console.print(
                    f"  {article_count:3d} articles  "
                    f"{llm_calls:2d} LLM calls  "
                    f"${cost:6.3f}",
                    style="cyan"
                )

                node_metrics[node_name] = {
                    "articles": article_count,
                    "llm_calls": llm_calls,
                    "cost": cost,
                }

        console.print("\n" + "━" * 70)

        # Final summary before interrupt
        if final_state:
            total_articles = len(final_state.get("articles", []))
            total_cost = final_state.get("estimated_cost_usd", 0.0)
            total_llm = final_state.get("llm_call_count", 0)
            elapsed = (datetime.now() - start_time).total_seconds()

            console.print(f"\n[bold green]✓ Autonomous phase complete ({elapsed:.1f}s)[/bold green]")
            console.print(f"  • Articles in draft: {total_articles}")
            console.print(f"  • LLM calls made: {total_llm}")
            console.print(f"  • Estimated cost: ${total_cost:.3f}")

        # Check for interrupt
        try:
            state_snapshot = graph.get_state(config)
            if state_snapshot and state_snapshot.next:
                console.print(f"\n[bold cyan]⏸️  PAUSED AT HUMAN REVIEW CHECKPOINT[/bold cyan]")
                console.print(f"[cyan]Next node:[/cyan] {state_snapshot.next[0] if state_snapshot.next else 'unknown'}\n")
                console.print("[yellow]" + "━" * 70 + "[/yellow]")
                console.print("[bold yellow]📋 ARIA has drafted your newsletter. Please review and approve.[/bold yellow]")
                console.print("[yellow]" + "━" * 70 + "[/yellow]\n")

                # Save state to JSON file for Streamlit to read
                def json_serializer(obj):
                    """Custom JSON serializer for non-serializable objects."""
                    if isinstance(obj, datetime):
                        return obj.isoformat()
                    return str(obj)

                # Only include articles that were actually selected and summarized
                # (filter to only articles that have summary_text)
                all_articles = final_state.get("articles", []) if final_state else []
                selected_articles = [a for a in all_articles if a.get("summary_text") and a.get("summary_text").strip()]

                state_to_save = {
                    "run_id": run_id,
                    "articles": selected_articles,  # Only the summarized (selected) articles
                    "draft_newsletter": final_state.get("draft_newsletter", "") if final_state else "",
                    "timestamp": start_time.isoformat(),
                }
                with open(".aria_state.json", "w") as f:
                    json.dump(state_to_save, f, indent=2, default=json_serializer)

                # Launch Streamlit automatically
                streamlit_process = launch_streamlit_review(run_id, console)

                try:
                    # Loop for multiple review rounds (approve, re-rank, etc.)
                    while True:
                        # Wait for user decision in Streamlit
                        reviewed_state = wait_for_review_decision(graph, config, console)

                        # Resume graph from checkpoint
                        final_state, hit_interrupt_again = resume_from_checkpoint(graph, config, reviewed_state, console)

                        # If graph hit human_review interrupt again, refresh UI and loop
                        if hit_interrupt_again:
                            console.print("\n[bold cyan]⏸️  PAUSED AT HUMAN REVIEW CHECKPOINT (RE-RUN)[/bold cyan]")
                            console.print("[cyan]Refreshing review interface with updated articles...[/cyan]\n")

                            # Save updated state to JSON for Streamlit to read
                            all_articles = final_state.get("articles", []) if final_state else []
                            selected_articles = [a for a in all_articles if a.get("summary_text") and a.get("summary_text").strip()]

                            state_to_save = {
                                "run_id": run_id,
                                "articles": selected_articles,
                                "draft_newsletter": final_state.get("draft_newsletter", "") if final_state else "",
                                "timestamp": start_time.isoformat(),
                            }
                            with open(".aria_state.json", "w") as f:
                                json.dump(state_to_save, f, indent=2, default=json_serializer)

                            # Signal Streamlit to refresh (clear decision file if it exists)
                            try:
                                if os.path.exists(".aria_review_decision.json"):
                                    os.remove(".aria_review_decision.json")
                            except Exception:
                                pass

                            # Loop back to wait for next decision
                            continue

                        # No more interrupts, exit loop
                        break

                    # Summary
                    if final_state:
                        total_articles = len(final_state.get("articles", []))
                        total_cost = final_state.get("estimated_cost_usd", 0.0)
                        total_llm = final_state.get("llm_call_count", 0)
                        elapsed = (datetime.now() - start_time).total_seconds()

                        console.print(f"\n[bold green]✓ Pipeline completed ({elapsed:.1f}s total)[/bold green]")
                        console.print(f"  • Total articles: {total_articles}")
                        console.print(f"  • Total LLM calls: {total_llm}")
                        console.print(f"  • Total cost: ${total_cost:.3f}\n")

                        if final_state.get("published"):
                            console.print("[bold green]✅ Newsletter published successfully![/bold green]")

                            # Show email status
                            message_id = final_state.get("message_id", "")
                            if message_id.startswith("simulated_"):
                                console.print("[yellow]⚠️  Email not sent (Gmail not configured)[/yellow]")
                                console.print("[yellow]   → Set up Gmail credentials to enable email delivery[/yellow]")
                            else:
                                console.print(f"[green]📧 Email sent (Gmail API message_id: {message_id})[/green]")

                            # Show local file path
                            console.print("[cyan]📁 HTML saved locally to:[/cyan]")
                            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                            console.print(f"[cyan]   newsletters/{timestamp}/newsletter.html[/cyan]\n")
                        else:
                            console.print("[bold yellow]⚠️  Newsletter not published[/bold yellow]\n")

                finally:
                    # Keep Streamlit running so completion message stays visible
                    # User can close it manually when ready, or run python3 main.py again
                    console.print("\n[cyan]📱 Streamlit is still running at http://localhost:8501[/cyan]")
                    console.print("[cyan]   You can close it when ready, or run 'python3 main.py' again[/cyan]\n")
                    logger.info("Streamlit kept running - user can close manually or re-run pipeline")

            else:
                console.print("\n[bold green]✓ Pipeline completed (full execution)[/bold green]\n")
        except Exception as e:
            logger.warning(f"Could not check checkpoint state: {e}")
            console.print("\n[bold green]✓ Pipeline executed (checkpoint details unavailable)[/bold green]\n")

    except Exception as e:
        console.print(f"\n[bold red]✗ Pipeline failed:[/bold red]")
        console.print(f"[red]{type(e).__name__}: {str(e)}[/red]\n")
        logger.exception(f"Pipeline error: {e}")
        raise


if __name__ == "__main__":
    main()
