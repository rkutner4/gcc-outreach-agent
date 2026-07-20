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
    from agent.gmail_sender import gmail_status
    from agent.whatsapp_session import is_linked

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
            "gmail": gmail_status(settings),
            "whatsapp_linked": is_linked(settings),
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
    """Run Stage 1–2, enrich, compose, and send (respects dry-run / pause)."""
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


@app.command("gmail-login")
def gmail_login(
    verify: bool = typer.Option(
        True,
        "--verify/--no-verify",
        help="Call Gmail profile API after OAuth to confirm the linked mailbox",
    ),
) -> None:
    """Run Gmail OAuth in the browser and save a refresh token locally."""
    from agent.gmail_sender import gmail_status, login_instructions, verify_gmail_account

    settings = get_settings()
    print(login_instructions(settings))
    status = gmail_status(settings)
    if not status["client_secret_exists"]:
        print(
            "[red]Missing OAuth client JSON.[/red]\n"
            f"Expected at: {status['client_secret_path']}"
        )
        raise typer.Exit(code=1)

    if verify:
        try:
            profile = verify_gmail_account(settings)
        except FileNotFoundError as exc:
            print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
        except Exception as exc:  # noqa: BLE001
            print(f"[red]Gmail authorization failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        print("[green]Gmail authorized.[/green]")
        print(profile)
    else:
        from agent.gmail_sender import authorize_gmail

        authorize_gmail(settings)
        print("[green]Gmail token saved.[/green]")

    print(gmail_status(settings))
    if not settings.sender_email:
        print(
            "[yellow]Tip:[/yellow] set SENDER_EMAIL in .env so outbound messages "
            "include the correct From header."
        )


@app.command("whatsapp-login")
def whatsapp_login(
    phone_hint: str = typer.Option("", help="Optional phone hint for your own number"),
) -> None:
    """Create/link a personal WhatsApp session marker (QR/backend placeholder)."""
    from agent.whatsapp_session import login_instructions, mark_linked

    print(login_instructions())
    payload = mark_linked(phone_hint=phone_hint)
    print("[green]Session marker written.[/green]")
    print(payload)


@app.command("poll-inbound")
def poll_inbound_cmd() -> None:
    """Detect Gmail replies for awareness only — never auto-replies."""
    from agent.inbound_monitor import poll_inbound

    init_db()
    Session = get_session_factory()
    with Session() as db:
        print(poll_inbound(db))


@app.command("serve")
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    schedule: bool = typer.Option(False, help="Enable daily 09:00 prospect job"),
) -> None:
    """Run the web dashboard."""
    import uvicorn

    if schedule:
        from agent.scheduler import start_scheduler

        start_scheduler()
    uvicorn.run("dashboard.app:app", host=host, port=port, reload=not schedule)


if __name__ == "__main__":
    app()
