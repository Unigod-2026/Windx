"""Brand-mention extraction pipeline tests.

The molizhishu sync polling path is the one that exercises the
"answer_content landed after the first extraction" branch, so these
tests focus on the SKIPPED → PENDING promotion and on the idempotency
of re-runs against the same answer. The LLM pass itself is mocked so
the test runs without an LLM endpoint.

Same SQLite in-memory pattern as :mod:`tests.test_scheduler` and
:mod:`tests.test_sync`: a throwaway engine + sessionmaker patched
into ``app.db.get_session_factory``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Customer,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPrompt,
    ScheduleRun,
    Subtask,
    Task,
)
from app.models.common import now_local
from app.models.enums import ExtractStatus, RunStatus, RunTrigger
from app.models.project import BrandMention
from app.services.extraction import (
    _regex_pass,
    extract_brand_mentions,
)
from app.services.extraction import (
    _ExtractionContext as Ctx,
)

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestSessionLocal = sessionmaker(
    bind=test_engine, autoflush=False, autocommit=False, future=True
)


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch):
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(
        "app.services.extraction.get_session_factory", lambda: TestSessionLocal
    )
    yield
    Base.metadata.drop_all(test_engine)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _seed_full_project(answer_text: str = "玛舒拉沙韦治疗流感效果很好"):
    """Seed project 4-style layout: brand + 2 competitors + a keyword.

    Returns ``(task_id, subtask_id)`` so the test can call the
    extraction API directly against the subtask.
    """
    with TestSessionLocal() as db:
        cust = Customer(name="Acme", code="ACME")
        db.add(cust)
        db.flush()
        proj = Project(
            customer_id=cust.id,
            name="青峰医药",
            code="QF",
            brand="伊速达",
            aliases=["玛舒拉沙韦", "小青盒"],
        )
        db.add(proj)
        db.flush()
        db.add_all([
            ProjectCompetitor(project_id=proj.id, name="奥司他韦", aliases=[]),
            ProjectCompetitor(project_id=proj.id, name="玛巴洛沙韦", aliases=["速福达"]),
            ProjectKeyword(project_id=proj.id, keyword="流感"),
            ProjectPrompt(project_id=proj.id, prompt="哪个流感药好?", sort=1),
        ])
        run = ScheduleRun(
            project_id=proj.id,
            slot_index=0,
            trigger_type=RunTrigger.MANUAL,
            triggered_at=now_local(),
            started_at=now_local(),
            status=RunStatus.RUNNING,
        )
        db.add(run)
        db.flush()
        task = Task(
            task_id="t" * 32,
            status="completed",
            customer_id=cust.id,
            project_id=proj.id,
            schedule_run_id=run.id,
            total_items=1,
            completed_items=1,
        )
        db.add(task)
        sub = Subtask(
            task_id=task.task_id,
            subtask_id="s" * 32,
            platform="yuanbao",
            mode="standard",
            prompt="哪个流感药好?",
            status="completed",
            answer_content=answer_text,
        )
        db.add(sub)
        db.commit()
        return task.task_id, sub.subtask_id, proj.id


def _make_ctx(answer: str, *, subtask_id: str = "s" * 32,
              task_id: str = "t" * 32, project_id: int = 1,
              subtask_status: str | None = "completed") -> Ctx:
    """Build a context object directly so we can drive ``_regex_pass``."""
    return Ctx(
        subtask_id=subtask_id,
        task_id=task_id,
        project_id=project_id,
        customer_id=1,
        prompt="哪个流感药好?",
        platform="yuanbao",
        answer_content=answer,
        subtask_status=subtask_status,
        brand_targets=[
            ("伊速达", ["玛舒拉沙韦", "小青盒"]),
            ("奥司他韦", []),
            ("玛巴洛沙韦", ["速福达"]),
        ],
        keywords=["流感"],
    )


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_regex_pass_writes_skipped_when_no_brand_in_answer():
    """Empty / brand-less answers get SKIPPED, not PENDING."""
    task_id, sub_id, proj_id = _seed_full_project(answer_text="暂时没有")
    ctx = _make_ctx("暂时没有", subtask_id=sub_id,
                    task_id=task_id, project_id=proj_id)
    with TestSessionLocal() as db:
        upserted = _regex_pass(db, ctx)
        db.commit()
    assert upserted == 3
    with TestSessionLocal() as db:
        rows = db.scalars(select(BrandMention).where(
            BrandMention.subtask_id == sub_id
        )).all()
        statuses = {r.brand_canonical: r.extract_status for r in rows}
        assert statuses == {
            "伊速达": ExtractStatus.SKIPPED,
            "奥司他韦": ExtractStatus.SKIPPED,
            "玛巴洛沙韦": ExtractStatus.SKIPPED,
        }


def test_regex_pass_writes_pending_for_matched_brand():
    """First extraction on a real answer → matched rows go PENDING."""
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="伊速达(玛舒拉沙韦)对甲流很有效"
    )
    ctx = _make_ctx("伊速达(玛舒拉沙韦)对甲流很有效",
                    subtask_id=sub_id, task_id=task_id, project_id=proj_id)
    with TestSessionLocal() as db:
        _regex_pass(db, ctx)
        db.commit()
    with TestSessionLocal() as db:
        rows = db.scalars(select(BrandMention).where(
            BrandMention.subtask_id == sub_id
        )).all()
        statuses = {r.brand_canonical: (r.extract_status, r.mention_count)
                    for r in rows}
        assert statuses["伊速达"] == (ExtractStatus.PENDING, 1)
        assert statuses["奥司他韦"] == (ExtractStatus.SKIPPED, 0)
        assert statuses["玛巴洛沙韦"] == (ExtractStatus.SKIPPED, 0)


def test_regex_pass_bumps_skipped_to_pending_when_text_now_matches():
    """Regression for the polling-after-submit race.

    Real-world bug: ``run_project`` used to run extraction against
    an empty ``answer_content`` (molizhishu mode), so every brand
    row landed as SKIPPED. The polling sync then filled in the real
    answer and called extraction again — but the existing code path
    only refreshed ``mention_count`` without promoting the row back
    to PENDING, so the LLM pass never ran. This test pins the fix.
    """
    task_id, sub_id, proj_id = _seed_full_project(answer_text="")
    # First pass: empty text. All SKIPPED.
    empty_ctx = _make_ctx("", subtask_id=sub_id,
                          task_id=task_id, project_id=proj_id)
    with TestSessionLocal() as db:
        _regex_pass(db, empty_ctx)
        db.commit()
    with TestSessionLocal() as db:
        before = {r.brand_canonical: r.extract_status
                  for r in db.scalars(select(BrandMention).where(
                      BrandMention.subtask_id == sub_id
                  )).all()}
        assert before == {
            "伊速达": ExtractStatus.SKIPPED,
            "奥司他韦": ExtractStatus.SKIPPED,
            "玛巴洛沙韦": ExtractStatus.SKIPPED,
        }

    # Second pass: the real answer lands via the polling sync. The
    # self brand (matched via alias 玛舒拉沙韦) must be promoted to
    # PENDING so the LLM pass picks it up. The two unmatched brands
    # stay SKIPPED.
    real_ctx = _make_ctx("吃玛舒拉沙韦治疗甲流", subtask_id=sub_id,
                         task_id=task_id, project_id=proj_id)
    with TestSessionLocal() as db:
        _regex_pass(db, real_ctx)
        db.commit()
    with TestSessionLocal() as db:
        after = {r.brand_canonical: (r.extract_status, r.mention_count)
                 for r in db.scalars(select(BrandMention).where(
                     BrandMention.subtask_id == sub_id
                 )).all()}
        assert after["伊速达"] == (ExtractStatus.PENDING, 1)
        assert after["奥司他韦"] == (ExtractStatus.SKIPPED, 0)
        assert after["玛巴洛沙韦"] == (ExtractStatus.SKIPPED, 0)


def test_regex_pass_does_not_downgrade_success_rows():
    """A SUCCESS row stays SUCCESS even if a later re-extraction sees
    empty / brand-less text — the LLM pass has already populated the
    expensive fields and we don't want a stray re-run to wipe them.
    """
    task_id, sub_id, proj_id = _seed_full_project(answer_text="伊速达治疗流感")
    ctx = _make_ctx("伊速达治疗流感", subtask_id=sub_id,
                    task_id=task_id, project_id=proj_id)
    with TestSessionLocal() as db:
        _regex_pass(db, ctx)
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        row.extract_status = ExtractStatus.SUCCESS
        row.rank_position = 1
        row.sentiment_score = 0.9
        db.commit()

    # Re-extract against an answer that doesn't mention 伊速达.
    second_ctx = _make_ctx("其他无关回答", subtask_id=sub_id,
                           task_id=task_id, project_id=proj_id)
    with TestSessionLocal() as db:
        _regex_pass(db, second_ctx)
        db.commit()
    with TestSessionLocal() as db:
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        assert row.extract_status == ExtractStatus.SUCCESS
        # Heavy fields preserved.
        assert row.rank_position == 1
        assert row.sentiment_score == 0.9
        # ``mention_count`` is informational; reflecting the current
        # text is the honest thing to do.
        assert row.mention_count == 0


def test_extract_brand_mentions_end_to_end_no_llm_call_on_skipped_only(monkeypatch):
    """When the answer mentions no brand, the LLM pass should NOT be
    called at all (no rows in PENDING). Patches the LLM client builder
    so a stray LLM hit would surface as a test failure.
    """
    task_id, sub_id, proj_id = _seed_full_project(answer_text="什么也没提到")

    def boom(*_args, **_kwargs):
        raise AssertionError("LLM client should not be built when no PENDING rows")

    monkeypatch.setattr(
        "app.services.extraction._build_llm_client", boom
    )
    result = extract_brand_mentions(sub_id)
    # ``upserted`` is 3 (we wrote a row per brand) but LLM didn't run.
    assert result.rows_upserted == 3
    assert result.rows_succeeded == 0
    assert result.rows_failed == 0


def test_extract_brand_mentions_runs_llm_on_pending(monkeypatch):
    """When matched brands exist, the LLM pass IS called and the
    returned payload promotes the row to SUCCESS. The LLM client is
    replaced with a stub that returns a canned ``record_extraction``
    payload via the structured-output channel.
    """
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="小青盒(玛舒拉沙韦)是治疗甲流的好药"
    )

    async def fake_ask(self, *, system, user_prompt, tools=None, max_tokens=None):
        # The real extractor reads ``structured`` to fill rank / sentiment.
        return "", [{"name": "record_extraction", "input": {}}], {
            "rank_position": 1,
            "sentiment_score": 0.9,
            "is_recommended": True,
            "concern_hits": ["流感"],
        }

    monkeypatch.setattr("app.services.llm_client.LLMClient.ask", fake_ask)
    result = extract_brand_mentions(sub_id)
    assert result.rows_succeeded >= 1
    with TestSessionLocal() as db:
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        assert row.extract_status == ExtractStatus.SUCCESS
        assert row.rank_position == 1
        assert row.sentiment_score == 0.9
        assert row.is_recommended is True
        assert row.concern_hits_json == ["流感"]


def _seed_failed_subtask(answer_text: str = "上游接口超时,请稍后重试"):
    """Same project layout as ``_seed_full_project`` but the subtask
    is in ``status='failed'`` with an ``errorMessage``-style answer.
    """
    with TestSessionLocal() as db:
        cust = Customer(name="Acme", code="ACME")
        db.add(cust)
        db.flush()
        proj = Project(
            customer_id=cust.id,
            name="青峰医药",
            code="QF",
            brand="伊速达",
            aliases=["玛舒拉沙韦", "小青盒"],
        )
        db.add(proj)
        db.flush()
        db.add_all([
            ProjectCompetitor(project_id=proj.id, name="奥司他韦", aliases=[]),
            ProjectCompetitor(project_id=proj.id, name="玛巴洛沙韦", aliases=["速福达"]),
            ProjectKeyword(project_id=proj.id, keyword="流感"),
            ProjectPrompt(project_id=proj.id, prompt="哪个流感药好?", sort=1),
        ])
        run = ScheduleRun(
            project_id=proj.id,
            slot_index=0,
            trigger_type=RunTrigger.MANUAL,
            triggered_at=now_local(),
            started_at=now_local(),
            status=RunStatus.RUNNING,
        )
        db.add(run)
        db.flush()
        task = Task(
            task_id="t" * 32,
            status="failed",
            customer_id=cust.id,
            project_id=proj.id,
            schedule_run_id=run.id,
            total_items=1,
            completed_items=0,
            failed_items=1,
        )
        db.add(task)
        sub = Subtask(
            task_id=task.task_id,
            subtask_id="s" * 32,
            platform="yuanbao",
            mode="standard",
            prompt="哪个流感药好?",
            status="failed",
            answer_content=answer_text,
            error_message=answer_text,
        )
        db.add(sub)
        db.commit()
        return task.task_id, sub.subtask_id, proj.id


def test_extract_skips_llm_for_failed_subtask(monkeypatch):
    """Failed subtasks get one SKIPPED row per brand target with
    mention_count=0 and all LLM-derived fields NULL. The LLM client
    must NOT be built — patching the builder to raise surfaces a stray
    LLM hit as a test failure.
    """
    task_id, sub_id, proj_id = _seed_failed_subtask()

    def boom(*_args, **_kwargs):
        raise AssertionError(
            "LLM client should not be built for failed subtasks"
        )

    monkeypatch.setattr(
        "app.services.extraction._build_llm_client", boom
    )
    result = extract_brand_mentions(sub_id)

    assert result.rows_upserted == 3
    assert result.rows_succeeded == 0
    assert result.rows_failed == 0

    with TestSessionLocal() as db:
        rows = db.scalars(select(BrandMention).where(
            BrandMention.subtask_id == sub_id
        )).all()
        assert len(rows) == 3
        for row in rows:
            assert row.mention_count == 0
            assert row.extract_status == ExtractStatus.SKIPPED
            # LLM-derived fields all NULL — no point scoring an error.
            assert row.rank_position is None
            assert row.sentiment_score is None
            assert row.is_recommended is None
            assert row.concern_hits_json is None


def test_failed_subtask_pass_idempotent_does_not_clobber_success():
    """If extraction has somehow already produced a SUCCESS row on a
    subtask that later flips to 'failed', the failed re-classification
    must NOT wipe the heavy fields. Real-world this shouldn't happen
    (status moves one direction only), but the contract matters for
    re-runs / backfills.
    """
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="伊速达治疗流感"
    )
    with TestSessionLocal() as db:
        _regex_pass(db, _make_ctx("伊速达治疗流感",
                                  subtask_id=sub_id, task_id=task_id,
                                  project_id=proj_id))
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        row.extract_status = ExtractStatus.SUCCESS
        row.rank_position = 1
        row.sentiment_score = 0.9
        row.is_recommended = True
        row.concern_hits_json = ["流感"]
        db.commit()

    # Flip the subtask to failed + re-run extraction.
    with TestSessionLocal() as db:
        sub = db.get(Subtask, sub_id)
        sub.status = "failed"
        sub.answer_content = "上游接口超时"
        db.commit()

    extract_brand_mentions(sub_id)

    with TestSessionLocal() as db:
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        # SUCCESS + heavy fields preserved even though the subtask is
        # now classified as failed.
        assert row.extract_status == ExtractStatus.SUCCESS
        assert row.rank_position == 1
        assert row.sentiment_score == 0.9
        assert row.is_recommended is True
        assert row.concern_hits_json == ["流感"]


def test_extract_does_not_skip_llm_for_non_failed_subtask(monkeypatch):
    """Sanity check: a non-failed subtask (e.g. status='completed' or
    status=None) still flows through the normal regex + LLM path. We
    patch the LLM builder to raise so the SUCCESS promotion only
    happens via the real path, not via the failed fast path.
    """
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="小青盒(玛舒拉沙韦)是治疗甲流的好药"
    )

    async def fake_ask(self, *, system, user_prompt, tools=None, max_tokens=None):
        return "", [{"name": "record_extraction", "input": {}}], {
            "rank_position": 2,
            "sentiment_score": 0.8,
            "is_recommended": True,
            "concern_hits": ["流感"],
        }

    monkeypatch.setattr("app.services.llm_client.LLMClient.ask", fake_ask)
    extract_brand_mentions(sub_id)

    with TestSessionLocal() as db:
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        assert row.extract_status == ExtractStatus.SUCCESS
        assert row.rank_position == 2


# --------------------------------------------------------------------------
# Per-row LLM retry tests
# --------------------------------------------------------------------------


def test_llm_retry_succeeds_on_third_attempt(monkeypatch):
    """First 2 attempts fail, 3rd succeeds → row marked SUCCESS.

    Asserts the per-row retry counter via a mutable closure on the
    fake. Sleep is monkey-patched to a no-op so the test doesn't
    actually wait 20s.
    """
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="小青盒(玛舒拉沙韦)是治疗甲流的好药"
    )

    attempts = {"n": 0}

    async def fake_ask(self, *, system, user_prompt, tools=None, max_tokens=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            from app.services.llm_client import LLMError

            raise LLMError(f"transient failure {attempts['n']}")
        return "", [{"name": "record_extraction", "input": {}}], {
            "rank_position": 1,
            "sentiment_score": 0.9,
            "is_recommended": True,
            "concern_hits": ["流感"],
        }

    monkeypatch.setattr("app.services.llm_client.LLMClient.ask", fake_ask)
    # Skip the 10s sleep so the test runs in milliseconds.
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.services.extraction.asyncio.sleep", no_sleep)

    result = extract_brand_mentions(sub_id)
    assert attempts["n"] == 3, "expected exactly 3 LLM calls (2 fail + 1 success)"
    assert result.rows_succeeded >= 1
    assert result.rows_failed == 0

    with TestSessionLocal() as db:
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        assert row.extract_status == ExtractStatus.SUCCESS
        assert row.extract_error is None
        assert row.mention_count == 1
        assert row.rank_position == 1


def test_llm_retry_marks_failed_after_3_attempts(monkeypatch):
    """All 3 attempts fail → row marked FAILED, mention_count=0,
    extract_error set. Row stays in the table (denominator preserved).
    """
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="小青盒(玛舒拉沙韦)是治疗甲流的好药"
    )

    attempts = {"n": 0}

    async def fake_ask(self, *, system, user_prompt, tools=None, max_tokens=None):
        attempts["n"] += 1
        from app.services.llm_client import LLMError

        raise LLMError(f"permanent failure {attempts['n']}")

    monkeypatch.setattr("app.services.llm_client.LLMClient.ask", fake_ask)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.services.extraction.asyncio.sleep", no_sleep)

    result = extract_brand_mentions(sub_id)
    assert attempts["n"] == 3, "expected exactly 3 LLM attempts"
    # 伊速达 was matched by regex so it gets retried; the other two brands
    # stayed SKIPPED (no LLM call for them).
    assert result.rows_failed >= 1

    with TestSessionLocal() as db:
        rows = db.scalars(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
        )).all()
        assert len(rows) == 3, "denominator: row per (subtask × brand) preserved"
        matched = next(r for r in rows if r.brand_canonical == "伊速达")
        assert matched.extract_status == ExtractStatus.FAILED
        assert matched.mention_count == 0, "treated as no mention per policy"
        assert matched.extract_error is not None
        assert "3次" in matched.extract_error or "3 " in matched.extract_error
        # LLM-derived fields stay NULL.
        assert matched.rank_position is None
        assert matched.sentiment_score is None
        assert matched.is_recommended is None
        assert matched.concern_hits_json is None
        assert matched.raw_extraction is None
        # Unmatched brands stay SKIPPED (no LLM attempt).
        for r in rows:
            if r.brand_canonical != "伊速达":
                assert r.extract_status == ExtractStatus.SKIPPED


def test_llm_retry_also_retries_when_model_doesnt_call_tool(monkeypatch):
    """"LLM returned but didn't call record_extraction" counts as a
    failure for retry purposes — the model just didn't cooperate this
    attempt. After 3 empty returns the row is marked FAILED.
    """
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="小青盒(玛舒拉沙韦)是治疗甲流的好药"
    )

    attempts = {"n": 0}

    async def fake_ask(self, *, system, user_prompt, tools=None, max_tokens=None):
        attempts["n"] += 1
        # Return text + transcript without the structured tool call.
        return "I'll just describe what I see.", [], None

    monkeypatch.setattr("app.services.llm_client.LLMClient.ask", fake_ask)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.services.extraction.asyncio.sleep", no_sleep)

    extract_brand_mentions(sub_id)
    assert attempts["n"] == 3

    with TestSessionLocal() as db:
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        assert row.extract_status == ExtractStatus.FAILED
        assert row.mention_count == 0
        assert "record_extraction" in (row.extract_error or "")


def test_regex_pass_bumps_failed_to_pending_when_text_matches():
    """Re-running extraction on a FAILED row whose text matches the
    brand must promote it back to PENDING so the LLM pass can retry.
    This is the trigger half of the retry semantics: sync sees FAILED,
    re-runs extract, regex pass bumps it.
    """
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="伊速达治疗流感"
    )
    # First pass: regex matched, LLM "failed" (we'll just set the row state).
    with TestSessionLocal() as db:
        _regex_pass(db, _make_ctx("伊速达治疗流感",
                                  subtask_id=sub_id, task_id=task_id,
                                  project_id=proj_id))
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        row.extract_status = ExtractStatus.FAILED
        row.mention_count = 0
        row.extract_error = "previous LLM outage"
        db.commit()

    # Re-run extraction: regex should bump FAILED→PENDING, clear extract_error.
    with TestSessionLocal() as db:
        _regex_pass(db, _make_ctx("伊速达治疗流感",
                                  subtask_id=sub_id, task_id=task_id,
                                  project_id=proj_id))
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        assert row.extract_status == ExtractStatus.PENDING
        assert row.mention_count == 1
        assert row.extract_error is None


def test_regex_pass_keeps_failed_when_text_no_longer_matches():
    """If the answer changed and no longer mentions the brand, a FAILED
    row stays FAILED (with old extract_error). No point re-running LLM
    against a non-mention — the LLM pass won't pick it up because
    status stays FAILED.
    """
    task_id, sub_id, proj_id = _seed_full_project(
        answer_text="伊速达治疗流感"
    )
    with TestSessionLocal() as db:
        _regex_pass(db, _make_ctx("伊速达治疗流感",
                                  subtask_id=sub_id, task_id=task_id,
                                  project_id=proj_id))
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        row.extract_status = ExtractStatus.FAILED
        row.extract_error = "previous LLM outage"
        db.commit()

    # Re-run with an answer that doesn't mention the brand.
    with TestSessionLocal() as db:
        _regex_pass(db, _make_ctx("其它无关回答",
                                  subtask_id=sub_id, task_id=task_id,
                                  project_id=proj_id))
        row = db.scalar(select(BrandMention).where(
            BrandMention.subtask_id == sub_id,
            BrandMention.brand_canonical == "伊速达",
        ))
        # Row stays FAILED — no bump because text doesn't match.
        assert row.extract_status == ExtractStatus.FAILED
        assert row.mention_count == 0
        # extract_error preserved (historical context for past failure).
        assert row.extract_error == "previous LLM outage"
