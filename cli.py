"""CLI entrypoint for power users (dashboard is primary control plane)."""

from __future__ import annotations

import typer
from rich import print

from agent.config import get_settings
from agent.db import PipelineState, get_session_factory, init_db

app = typer.Typer(help="GCC Institutional Wealth Outreach Agent CLI")


@app.command()
def init() -> None:
    """Create database tables and default pipeline state."""
    init_db()
    print("[green]Database initialized.[/green]")


@app.command()
def status() -> None:
    """Show pipeline + config summary."""
    init_db()
    settings = get_settings()
    Session = get_session_factory()
    with Session() as db:
        state = db.query(PipelineState).first()
    print(
        {
            "dry_run_env": settings.dry_run,
            "paused": state.paused if state else None,
            "dry_run_db": state.dry_run if state else None,
            "last_run_status": state.last_run_status if state else None,
            "email_daily_cap": settings.email_daily_cap,
            "whatsapp_daily_cap": settings.whatsapp_daily_cap,
            "geography": list(settings.target_countries),
        }
    )


@app.command()
def pause() -> None:
    init_db()
    Session = get_session_factory()
    with Session() as db:
        state = db.query(PipelineState).first()
        if state:
            state.paused = True
            db.commit()
    print("[yellow]Pipeline paused.[/yellow]")


@app.command()
def resume() -> None:
    init_db()
    Session = get_session_factory()
    with Session() as db:
        state = db.query(PipelineState).first()
        if state:
            state.paused = False
            db.commit()
    print("[green]Pipeline resumed.[/green]")


@app.command()
def prospect(
    query: str = typer.Argument(
        ...,
        help="Natural-language target, e.g. 'CIOs at GCC sovereign wealth holding companies'",
    ),
) -> None:
    """Run Stage 1 (companies) + Stage 2 (contacts). No approval gate."""
    from agent.pipeline import run_prospect

    result = run_prospect(query)
    print(result)


@app.command("list-companies")
def list_companies() -> None:
    """Print discovered holding companies."""
    from agent.db import HoldingCompany

    init_db()
    Session = get_session_factory()
    with Session() as db:
        rows = (
            db.query(HoldingCompany)
            .order_by(HoldingCompany.confidence_score.desc())
            .all()
        )
    for r in rows:
        print(
            f"{r.id}\t{r.confidence_score:.2f}\t{r.status}\t{r.country}\t{r.name}"
        )


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the web dashboard."""
    import uvicorn

    uvicorn.run("dashboard.app:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    app()
