import asyncio
import subprocess
import sys
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Optional

import typer

from app.logging_config import configure_logging

configure_logging()

app = typer.Typer(name="alt", help="ALT 한국 주식 자동매매 시스템 CLI")

# ── 서브커맨드 그룹 ──────────────────────────────────────────────

trader_app = typer.Typer(help="트레이딩 관련 명령어")
app.add_typer(trader_app, name="trader")

market_app = typer.Typer(help="시장 데이터 관련 명령어")
app.add_typer(market_app, name="market")

news_app = typer.Typer(help="뉴스 관련 명령어")
app.add_typer(news_app, name="news")

dart_app = typer.Typer(help="DART 공시 관련 명령어")
app.add_typer(dart_app, name="dart")

ws_app = typer.Typer(help="웹소켓 관련 명령어")
app.add_typer(ws_app, name="ws")


todo_app = typer.Typer(help="TODO 관련 명령어")
app.add_typer(todo_app, name="todo")

db_app = typer.Typer(help="데이터베이스 관련 명령어")
app.add_typer(db_app, name="db")

backfill_app = typer.Typer(help="데이터 보충 관련 명령어")
app.add_typer(backfill_app, name="backfill")

review_app = typer.Typer(help="일일 회고/리포트")
app.add_typer(review_app, name="review")


# ── 유틸리티 ─────────────────────────────────────────────────────

def _parse_stock_codes(stock_codes: Optional[str]) -> list[str] | None:
    """쉼표 구분 종목코드 문자열을 리스트로 파싱. None이면 None 반환."""
    if not stock_codes:
        return None
    return [code.strip() for code in stock_codes.split(",") if code.strip()]


async def _get_system_param(session, key: str, default: str) -> str:
    """SystemParameter에서 키에 해당하는 값을 조회. 없으면 default 반환."""
    from sqlalchemy import select

    from app.models.system_parameter import SystemParameter

    result = await session.execute(
        select(SystemParameter.value).where(SystemParameter.key == key)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else default


async def _get_target_stock_codes(session) -> list[str]:
    """TargetStock에서 활성화된 종목코드 목록 조회."""
    from sqlalchemy import select

    from app.models.target_stock import TargetStock

    result = await session.execute(
        select(TargetStock.stock_code).where(TargetStock.is_active.is_(True))
    )
    return list(result.scalars().all())


def _is_market_open(market_start: str, market_end: str) -> bool:
    """현재 시각이 장 시작/종료 시각 사이인지 확인."""
    now = datetime.now().time()
    try:
        start = dt_time.fromisoformat(market_start)
        end = dt_time.fromisoformat(market_end)
    except (ValueError, TypeError):
        start = dt_time(9, 0)
        end = dt_time(15, 30)
    return start <= now <= end


# ── trader ───────────────────────────────────────────────────────

@trader_app.command("run")
def trader_run(
    stock_codes: Optional[str] = typer.Option(
        None, "--stock-codes", help="쉼표 구분 종목코드 (미지정 시 TargetStock 전체)"
    ),
) -> None:
    """트레이딩 사이클 반복 실행."""

    async def _run() -> None:
        from app.database import async_session

        typer.echo("트레이더 시작...")
        while True:
            async with async_session() as session:
                interval = int(await _get_system_param(session, "trading_interval", "60"))
                market_start = await _get_system_param(session, "market_start_time", "09:00")
                market_end = await _get_system_param(session, "market_end_time", "15:30")

                codes = _parse_stock_codes(stock_codes)
                if codes is None:
                    codes = await _get_target_stock_codes(session)

                if not _is_market_open(market_start, market_end):
                    typer.echo(f"장 운영 시간 외입니다 ({market_start}~{market_end}). {interval}초 후 재확인...")
                    await asyncio.sleep(interval)
                    continue

                typer.echo(f"트레이딩 사이클 실행: {codes}")
                try:
                    from app.services.trader import run_trading_cycle

                    decision = await run_trading_cycle(session)
                    typer.echo(
                        f"트레이딩 사이클 완료: id={decision.id} "
                        f"result={decision.decision} "
                        f"error={decision.error_message or 'N/A'}"
                    )
                except Exception as exc:
                    typer.echo(f"트레이딩 사이클 오류: {exc}", err=True)

            await asyncio.sleep(interval)

    asyncio.run(_run())


# ── market ───────────────────────────────────────────────────────

@market_app.command("collect")
def market_collect(
    stock_codes: Optional[str] = typer.Option(
        None, "--stock-codes", help="쉼표 구분 종목코드 (미지정 시 TargetStock 전체)"
    ),
) -> None:
    """시장 스냅샷 수집 반복 실행."""

    async def _run() -> None:
        from app.database import async_session
        from app.services.market_collector import collect_market_snapshots

        typer.echo("시장 스냅샷 수집 시작...")
        while True:
            async with async_session() as session:
                interval = int(await _get_system_param(session, "market_snapshot_interval", "60"))
                codes = _parse_stock_codes(stock_codes)

                try:
                    results = await collect_market_snapshots(session, stock_codes=codes)
                    typer.echo(
                        f"시장 스냅샷 수집 완료: {len(results['stock_codes'])}종목, "
                        f"fetched={results['fetched_items']}, saved={results['saved_items']}"
                    )
                except Exception as exc:
                    typer.echo(f"시장 스냅샷 수집 오류: {exc}", err=True)

            await asyncio.sleep(interval)

    asyncio.run(_run())


# ── news ─────────────────────────────────────────────────────────

@news_app.command("collect")
def news_collect(
    stock_codes: Optional[str] = typer.Option(
        None, "--stock-codes", help="쉼표 구분 종목코드 (미지정 시 TargetStock 전체)"
    ),
) -> None:
    """뉴스 수집 반복 실행."""

    async def _run() -> None:
        from app.database import async_session
        from app.services.news_collector import collect_all_news

        typer.echo("뉴스 수집 시작...")
        while True:
            async with async_session() as session:
                interval = int(await _get_system_param(session, "news_interval", "300"))
                codes = _parse_stock_codes(stock_codes)

                results = await collect_all_news(session, stock_codes=codes)
                total_saved = sum(r.get("saved", 0) for r in results)
                total_fetched = sum(r.get("fetched", 0) for r in results)
                typer.echo(f"뉴스 수집 완료: {len(results)}종목, fetched={total_fetched}, saved={total_saved}")

            await asyncio.sleep(interval)

    asyncio.run(_run())


# ── dart ─────────────────────────────────────────────────────────

@dart_app.command("collect")
def dart_collect(
    stock_codes: Optional[str] = typer.Option(
        None, "--stock-codes", help="쉼표 구분 종목코드 (미지정 시 TargetStock 전체)"
    ),
) -> None:
    """DART 공시 수집 반복 실행."""

    async def _run() -> None:
        from app.database import async_session
        from app.services.dart_collector import collect_dart

        typer.echo("DART 공시 수집 시작...")
        while True:
            async with async_session() as session:
                interval = int(await _get_system_param(session, "dart_interval", "600"))
                codes = _parse_stock_codes(stock_codes)

                try:
                    results = await collect_dart(session, stock_codes=codes)
                    typer.echo(
                        f"DART 공시 수집 완료: {len(results['stock_codes'])}종목, "
                        f"fetched={results['fetched_items']}, saved={results['saved_items']}"
                    )
                except Exception as exc:
                    typer.echo(f"DART 공시 수집 오류: {exc}", err=True)

            await asyncio.sleep(interval)

    asyncio.run(_run())


# ── ws ───────────────────────────────────────────────────────────

@ws_app.command("subscribe")
def ws_subscribe(
    stock_codes: Optional[str] = typer.Option(
        None, "--stock-codes", help="쉼표 구분 종목코드 (미지정 시 TargetStock 전체)"
    ),
) -> None:
    """KIS 웹소켓 실시간 구독."""

    async def _run() -> None:
        from app.services.ws_collector import run_ws_subscriber

        codes = _parse_stock_codes(stock_codes)
        typer.echo("KIS 웹소켓 실시간 구독 시작...")
        try:
            await run_ws_subscriber(stock_codes=codes)
        except Exception as exc:
            typer.echo(f"웹소켓 구독 오류: {exc}", err=True)

    asyncio.run(_run())



# ── todo ─────────────────────────────────────────────────────────

@todo_app.command("list")
def todo_list() -> None:
    """TODO 목록 조회."""

    async def _run() -> None:
        from sqlalchemy import select

        from app.database import async_session
        from app.models.todo import Todo

        async with async_session() as session:
            result = await session.execute(select(Todo).order_by(Todo.created_at.desc()))
            todos = result.scalars().all()

            if not todos:
                typer.echo("등록된 TODO가 없습니다.")
                return

            for t in todos:
                typer.echo(f"[{t.status}] {t.id}. {t.title}")
                if t.description:
                    typer.echo(f"    {t.description}")

    asyncio.run(_run())


# ── db ───────────────────────────────────────────────────────────

@db_app.command("migrate")
def db_migrate() -> None:
    """Alembic 마이그레이션 실행 (alembic upgrade head)."""
    typer.echo("Alembic 마이그레이션 실행 중...")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    if result.returncode != 0:
        typer.echo(f"마이그레이션 실패 (exit code: {result.returncode})")
        raise typer.Exit(code=1)
    typer.echo("마이그레이션 완료.")


# ── review ───────────────────────────────────────────────────────

@review_app.command("daily")
def review_daily(
    date: Optional[str] = typer.Option(
        None, "--date", help="대상 날짜 (YYYY-MM-DD, KST). 미지정 시 오늘"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="텔레그램 전송 없이 출력만"),
) -> None:
    """장마감 일일 회고 생성 + 텔레그램 전송."""

    async def _run() -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.services.daily_review import generate_and_send_daily_review

        kst = ZoneInfo("Asia/Seoul")
        target_dt = datetime.now(tz=kst)
        if date:
            # accept YYYY-MM-DD
            target_dt = datetime.fromisoformat(date).replace(tzinfo=kst)

        msg = await generate_and_send_daily_review(target_dt, dry_run=dry_run)
        typer.echo(msg)

    asyncio.run(_run())


# ── backfill ─────────────────────────────────────────────────────

@backfill_app.command("candles")
def backfill_candles(
    stock_code: Optional[str] = typer.Option(
        None, "--stock-code", help="특정 종목코드 (미지정 시 활성 종목 전체)"
    ),
    date: Optional[str] = typer.Option(
        None, "--date", help="대상 날짜 (YYYY-MM-DD, KST). 미지정 시 오늘"
    ),
) -> None:
    """KIS 당일분봉조회 API로 빈 분봉 데이터를 보충한다 (수동 실행용)."""

    async def _run() -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.database import async_session
        from app.services.candle_backfill import backfill_candles as _backfill

        kst = ZoneInfo("Asia/Seoul")
        target_dt = datetime.now(tz=kst)
        if date:
            target_dt = datetime.fromisoformat(date).replace(tzinfo=kst)

        codes = [stock_code] if stock_code else None

        async with async_session() as session:
            results = await _backfill(session, stock_codes=codes, target_date=target_dt)
            typer.echo(
                f"분봉 보충 완료: {len(results['stock_codes'])}종목, "
                f"fetched={results['fetched']}, "
                f"inserted={results['inserted']}, "
                f"skipped={results['skipped']}"
            )

    asyncio.run(_run())


@backfill_app.command("candles-scheduler")
def backfill_candles_scheduler() -> None:
    """장 마감 후(15:40) 분봉 보충을 자동 실행하는 스케줄러."""

    async def _run() -> None:
        from zoneinfo import ZoneInfo

        from app.database import async_session
        from app.services.candle_backfill import backfill_candles as _backfill

        kst = ZoneInfo("Asia/Seoul")
        typer.echo("분봉 보충 스케줄러 시작...")

        while True:
            now = datetime.now(tz=kst)
            target_time = now.replace(hour=15, minute=40, second=0, microsecond=0)

            # 오늘 15:40 이전이면 오늘 15:40까지 대기
            # 오늘 15:40 이후이면 즉시 실행 후 내일 15:40까지 대기
            if now.time() < dt_time(15, 40):
                wait_seconds = (target_time - now).total_seconds()
                typer.echo(f"15:40까지 {int(wait_seconds)}초 대기...")
                await asyncio.sleep(wait_seconds)

            typer.echo(f"분봉 보충 실행: {datetime.now(tz=kst).isoformat()}")
            try:
                async with async_session() as session:
                    results = await _backfill(session, target_date=datetime.now(tz=kst))
                    typer.echo(
                        f"분봉 보충 완료: {len(results['stock_codes'])}종목, "
                        f"fetched={results['fetched']}, "
                        f"inserted={results['inserted']}, "
                        f"skipped={results['skipped']}"
                    )
            except Exception as exc:
                typer.echo(f"분봉 보충 오류: {exc}", err=True)

            # 다음 날 15:40까지 대기
            now = datetime.now(tz=kst)
            next_run = (now + timedelta(days=1)).replace(
                hour=15, minute=40, second=0, microsecond=0
            )
            wait_seconds = (next_run - now).total_seconds()
            typer.echo(f"다음 실행까지 {int(wait_seconds)}초 대기...")
            await asyncio.sleep(wait_seconds)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
