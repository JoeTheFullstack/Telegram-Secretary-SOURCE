"""Load test for Telegram-Secretary. Put this file in the project folder (next to README.md) and run:

    python loadtest.py

Options:
    --fast N           messages for the speed test without the LLM (default 500)
    --llm-calls N      sequential registrations with the real LLM, to time it (default 5)
    --burst N          messages that arrive at the same moment (default 10)
    --simulate-llm S   pretend the LLM takes S seconds per call (no Ollama needed)

It uses a temporary database. Your real data/secretary.db is not touched,
and nothing is sent to Telegram.
"""
import argparse
import os
import shutil
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.adapters.llm import LLMClient, OfflineLLM  # noqa: E402
from app.config import MIGRATIONS_DIR, load_config  # noqa: E402
from app.core.router import Router  # noqa: E402
from app.infra.db import connect  # noqa: E402
from app.infra.migrations import run_migrations  # noqa: E402

FIRST_USER = 1000


class SimulatedLLM:
    def __init__(self, seconds):
        self.seconds = seconds

    def chat_json(self, system, user):
        time.sleep(self.seconds)
        return {"full_name": "علی رضایی"}


class TimedLLM:
    """Wraps any LLM client and records how long each call takes."""

    def __init__(self, inner):
        self.inner = inner
        self.times = []
        self.errors = 0

    def chat_json(self, system, user):
        t0 = time.perf_counter()
        try:
            return self.inner.chat_json(system, user)
        except Exception:
            self.errors += 1
            raise
        finally:
            self.times.append(time.perf_counter() - t0)


def phone(i):
    return "09" + str(100000000 + i)


def message(i):
    return "مشتری جدید علی رضایی " + phone(i) + " بودجه 10 میلیارد زمین شمال"


def make_router(llm, workdir, n_users):
    conn = connect(os.path.join(workdir, "loadtest.db"))
    run_migrations(conn, MIGRATIONS_DIR)
    owners = list(range(FIRST_USER, FIRST_USER + n_users))
    return conn, Router(conn, llm, owner_ids=owners)


def send(router, user_index, text):
    t0 = time.perf_counter()
    replies = router.handle(FIRST_USER + user_index, "tester", text)
    return time.perf_counter() - t0, replies


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


def test_fast(workdir, count):
    print("\n=== Test 1: speed without the LLM (router + database only) ===")
    users = max(1, count // 2)
    conn, router = make_router(OfflineLLM(), workdir, users)
    times = []
    saved = 0
    start = time.perf_counter()
    for i in range(users):
        dt, _ = send(router, i, message(i))
        times.append(dt)
        dt, replies = send(router, i, "confirm")
        times.append(dt)
        if replies and "\u2705" in replies[0].text:
            saved += 1
    total = time.perf_counter() - start
    conn.close()
    print("messages handled : %d (customers saved: %d)" % (len(times), saved))
    print("total time       : %.2f s  ->  %.0f messages per second" % (total, len(times) / total))
    print("per message      : median %.1f ms, 95%% %.1f ms, worst %.1f ms" % (
        statistics.median(times) * 1000, percentile(times, 0.95) * 1000, max(times) * 1000))
    return len(times) / total


def test_llm(workdir, llm, calls):
    print("\n=== Test 2: how long does one registration take with the LLM? ===")
    conn, router = make_router(llm, workdir, calls + 1)
    durations = []
    for i in range(calls):
        dt, _ = send(router, i, message(5000 + i))
        durations.append(dt)
        label = "first call (model may need to load)" if i == 0 else "call %d" % (i + 1)
        print("%-36s %.1f s" % (label, dt))
    conn.close()
    warm = durations[1:] or durations
    avg = statistics.mean(warm)
    print("LLM errors/timeouts: %d" % llm.errors)
    print("average (without the first call): %.1f s" % avg)
    return avg


def test_burst(workdir, llm, burst, avg_llm):
    print("\n=== Test 3: %d messages arrive at the same moment ===" % burst)
    print("(the bot handles them one by one, like the real bot does)")
    conn, router = make_router(llm, workdir, burst + 1)
    t0 = time.perf_counter()
    finished = []
    for i in range(burst):
        send(router, i, message(9000 + i))
        finished.append(time.perf_counter() - t0)
    conn.close()
    for i in (0, burst // 2, burst - 1):
        print("message %-3d got its answer after %.1f s" % (i + 1, finished[i]))
    print("average wait: %.1f s, the last person waited: %.1f s" % (statistics.mean(finished), finished[-1]))
    print("\nEstimate for 50 messages at once: the last one waits about %.0f s (%.1f minutes)" % (
        50 * avg_llm, 50 * avg_llm / 60))
    print("Estimate for 5 messages at once : the last one waits about %.0f s" % (5 * avg_llm))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", type=int, default=500)
    parser.add_argument("--llm-calls", type=int, default=5)
    parser.add_argument("--burst", type=int, default=10)
    parser.add_argument("--simulate-llm", type=float, default=None)
    args = parser.parse_args()

    if args.simulate_llm is not None:
        llm = TimedLLM(SimulatedLLM(args.simulate_llm))
        print("LLM: SIMULATED, %.1f s per call" % args.simulate_llm)
    else:
        cfg = load_config()
        llm = TimedLLM(LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model, cfg.llm_timeout))
        print("LLM: model %s at %s (timeout %s s)" % (cfg.llm_model, cfg.llm_base_url, cfg.llm_timeout))

    workdir = tempfile.mkdtemp(prefix="secretary_loadtest_")
    try:
        test_fast(workdir, args.fast)
        avg = test_llm(workdir, llm, args.llm_calls)
        llm.times.clear()
        test_burst(workdir, llm, args.burst, avg)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("\nDone. Send me everything printed above.")


if __name__ == "__main__":
    main()
