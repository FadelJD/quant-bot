"""APScheduler wiring for a real run: the bar cycle plus daily and weekly report jobs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from kestrel.clock import Clock
from kestrel.live.runner import LiveRunner
from kestrel.logsetup import get_logger

log = get_logger(__name__)


def build_scheduler(runner: LiveRunner, clock: Clock) -> Any:  # pragma: no cover - needs a wall clock
    """Create a ``BlockingScheduler`` that fires ``run_cycle`` at each bar close.

    The cycle job reschedules itself from the market calendar so holidays and early closes are
    respected. The weekly report regenerates the HTML report on the configured weekday.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger

    sched = BlockingScheduler(timezone="UTC")

    def cycle() -> None:
        runner.run_cycle()
        schedule_next(clock.now())

    def schedule_next(after: datetime) -> None:
        nxt = runner.next_cycle_time(after)
        sched.add_job(cycle, DateTrigger(run_date=nxt), id="cycle", replace_existing=True, misfire_grace_time=runner.bar_seconds)
        log.info("next_cycle_scheduled", at=nxt.isoformat())

    def weekly() -> None:
        from kestrel.reporting.html import render_live_report

        path = render_live_report(runner)
        if path is not None:
            runner.store.record_report(runner.run_id, clock.now(), path)
            from kestrel.notify.base import Alert

            runner.notifier.send(Alert("weekly_report", "kestrel weekly report", "see attached", attachment=path))

    day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    hh, mm = (int(x) for x in runner.cfg.live.daily_report_time.split(":"))
    sched.add_job(weekly, CronTrigger(day_of_week=day_map[runner.cfg.live.weekly_report_day], hour=hh, minute=mm, timezone=runner.cfg.display_tz), id="weekly")
    schedule_next(clock.now() - timedelta(seconds=1))
    return sched
