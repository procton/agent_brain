"""`observatory` command line interface.

Subcommands (this MVP slice):
- demo-publish       : materialize explicitly synthetic events and write them
                       through the REAL spool (no agent integration needed)
- collector          : run the collector daemon that delivers spool events to
                       the backend
- opencode-listen    : passively subscribe to the local OpenCode background
                       service and publish sanitized events to the spool
- doctor             : local diagnostics (no payloads, no settings changes)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from backend.app import config as app_config
from backend.app.config import Settings
from collector.demo_events import FIXTURE_PATH, build_events, load_fixture
from collector.spool import Spool


def _settings_from_env(data_dir: str | None) -> Settings:
    if data_dir:
        import os

        os.environ["OBSERVATORY_DATA_DIR"] = data_dir
    return Settings()


def cmd_demo_publish(args: argparse.Namespace) -> int:
    settings = _settings_from_env(args.data_dir)
    fixture = load_fixture(Path(args.fixture) if args.fixture else FIXTURE_PATH)
    session_id = args.session_id or fixture["session_id"]
    events = build_events(fixture, session_id=session_id, repetitions=args.repetitions)
    spool = Spool(settings.spool_dir)
    for event in events:
        spool.publish(event.model_dump(mode="json"), event_id=event.event_id)
    print(
        f"published {len(events)} synthetic sanitized event(s) to spool {spool.root} (session {session_id})"
    )
    print("the collector will deliver them; nothing is sent to the dashboard from here.")
    return 0


def cmd_collector(args: argparse.Namespace) -> int:
    import asyncio

    from collector.daemon import CollectorDaemon

    settings = _settings_from_env(args.data_dir)
    credential = app_config.secret_from_file(settings.credential_path)
    spool = Spool(settings.spool_dir)
    daemon = CollectorDaemon(
        spool=spool,
        backend_base_url=args.backend,
        credential=credential,
        poll_interval_seconds=args.poll_interval,
    )

    async def run() -> int:
        if args.once:
            delivered = await daemon.run_until_idle()
            print(f"collector delivered {delivered} batch(es); spool: {spool.stats()}")
            return 0
        loop = asyncio.get_running_loop()

        def _stop() -> None:
            print("stopping collector (finishing current batch)...")
            daemon.request_stop()

        for sig in ("SIGINT", "SIGTERM"):
            import signal

            try:
                loop.add_signal_handler(getattr(signal, sig), _stop)
            except NotImplementedError:  # pragma: no cover - non-unix
                pass
        print(f"collector running; backend={args.backend} spool={spool.root} (Ctrl+C for clean shutdown)")
        await daemon.run_forever()
        print(
            f"collector stopped; batches={daemon.stats['batches_delivered']} "
            f"events={daemon.stats['events_delivered']}"
        )
        return 0

    return asyncio.run(run())


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = _settings_from_env(args.data_dir)
    checks: list[tuple[str, bool, str]] = []

    checks.append(("data_directory", settings.data_dir.exists(), str(settings.data_dir)))
    credential_ok = settings.credential_path.exists()
    checks.append(("ingest_credential", credential_ok, str(settings.credential_path)))
    code_ok = settings.dashboard_code_path.exists()
    checks.append(("dashboard_code_file", code_ok, str(settings.dashboard_code_path)))

    health_ok = False
    try:
        import httpx

        response = httpx.get(args.backend + "/api/health", timeout=3)
        health_ok = response.status_code == 200
    except Exception:
        health_ok = False
    checks.append(("backend_health", health_ok, f"{args.backend}/api/health"))

    spool = Spool(settings.spool_dir)
    stats = spool.stats()
    checks.append(("spool_pending", True, str(stats["pending"])))

    failed = False
    for name, ok, detail in checks:
        mark = "ok  " if ok else "FAIL"
        if not ok:
            failed = True
        print(f"[{mark}] {name}: {detail}")
    if code_ok:
        print()
        print("dashboard access code is in: ", settings.dashboard_code_path)
        print("(read it with `observatory doctor` or `cat` — never share it)")
    return 1 if failed else 0


def cmd_opencode_listen(args: argparse.Namespace) -> int:
    import asyncio

    from collector.opencode_listener import OpenCodeListener

    settings = _settings_from_env(args.data_dir)
    spool = Spool(settings.spool_dir)
    listener = OpenCodeListener(
        spool,
        settings=settings,
        server_url=args.server,
        password_file=Path(args.password_file) if args.password_file else None,
    )

    async def run() -> int:
        import signal

        loop = asyncio.get_running_loop()

        def _stop() -> None:
            print("stopping opencode-listen...")
            listener.request_stop()

        for sig in ("SIGINT", "SIGTERM"):
            try:
                loop.add_signal_handler(getattr(signal, sig), _stop)
            except NotImplementedError:  # pragma: no cover - non-unix
                pass

        if args.seconds:
            credentials = listener.discovery.credentials()
            if credentials is None:
                print(
                    "[opencode-listen] OpenCode service not discoverable — start OpenCode "
                    "or pass --server (+ OBSERVATORY_OPENCODE_PASSWORD)."
                )
                return 1
            await listener.stream_limited(
                auth_header=credentials[0],
                server_url=credentials[1],
                seconds=args.seconds,
            )
        else:
            print(
                f"opencode-listen running; spool={spool.root} (metadata-only capture, Ctrl+C for clean shutdown)"
            )
            await listener.run_forever()
        print(f"opencode-listen stopped; {listener.counters}")
        return 0

    return asyncio.run(run())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="observatory", description="local capture tooling for the observatory MVP"
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="override the application data directory (default: platform app data)",
    )
    parser.add_argument(
        "--backend",
        default=(f"http://127.0.0.1:{os.environ.get('OBSERVATORY_PORT', '8000')}"),
        help="backend base URL (default: http://127.0.0.1:$OBSERVATORY_PORT, else 8000)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo-publish", help="publish explicit synthetic events via the spool")
    demo.add_argument("--repetitions", type=int, default=1, help="fixture repetitions (default 1)")
    demo.add_argument("--fixture", default=None, help="custom fixture JSON path")
    demo.add_argument("--session-id", default=None, help="override source session id")
    demo.set_defaults(func=cmd_demo_publish)

    collector = sub.add_parser("collector", help="run the collector daemon")
    collector.add_argument(
        "--once",
        action="store_true",
        help="deliver everything queued, then exit",
    )
    collector.add_argument("--poll-interval", type=float, default=0.5)
    collector.set_defaults(func=cmd_collector)

    doctor = sub.add_parser("doctor", help="show local diagnostics")
    doctor.set_defaults(func=cmd_doctor)

    listen = sub.add_parser(
        "opencode-listen",
        help="passively capture OpenCode events into the spool",
    )
    listen.add_argument(
        "--server",
        default=None,
        help="OpenCode service URL (default: opencode service status discovery)",
    )
    listen.add_argument(
        "--password-file",
        default=None,
        help="service password JSON file (default: XDG config opencode/service.json)",
    )
    listen.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="capture for N seconds then exit (default: run until Ctrl+C)",
    )
    listen.set_defaults(func=cmd_opencode_listen)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
