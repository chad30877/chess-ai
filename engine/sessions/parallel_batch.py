"""有界的共用多程序派發；協調端依回報順序逐局保存。"""

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from queue import Empty
from time import monotonic

from engine.sessions.batch_workers import initialize_worker, run_work


def actual_workers(requested, work_count):
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise ValueError("同時對戰場數需為正整數")
    return min(requested, os.cpu_count() or 1, work_count, 61)


def run_parallel(*, work_count, workers, make_work, on_game, progress, control=None,
                 paused=None, bind_control=None, interval=0):
    """最多派發 workers 個工作，回報佇列最多容納 workers × 2 筆。"""
    context = multiprocessing.get_context("spawn")
    stop, resume = context.Event(), context.Event()
    resume.set()
    results = context.Queue(maxsize=workers * 2)
    if bind_control:
        bind_control(stop, resume)
    pending, active = {}, set()
    next_number = 1
    finished_count = finished_games = current_game = 0
    cooldowns = []
    error = None
    pool = None

    def notify():
        progress(dict(waiting_work=work_count - len(active) - finished_count, running_work=len(active),
                      finished_work=finished_count, finished_games=finished_games,
                      current_game=current_game))

    def receive(message):
        nonlocal finished_count, finished_games, current_game, error
        kind, number, payload = message
        if kind == "started":
            active.add(number)
        elif kind == "game_started":
            current_game = max(current_game, payload)
        elif kind == "game":
            finished_games += 1
            on_game(number, *payload)
        elif kind == "finished":
            if number in pending:
                pending.pop(number)
                active.discard(number)
                finished_count += 1
            if payload:
                error = error or RuntimeError(payload)
                stop.set()
                resume.set()
            elif interval:
                cooldowns.append(monotonic() + interval)
        notify()

    try:
        notify()
        last_tick = monotonic()
        while pending or (next_number <= work_count and not stop.is_set()):
            if control is not None and not control():
                stop.set()
                resume.set()
            is_paused = bool(paused and paused())
            now = monotonic()
            if is_paused:
                cooldowns[:] = [deadline + now - last_tick for deadline in cooldowns]
            else:
                cooldowns[:] = [deadline for deadline in cooldowns if deadline > now]
            last_tick = now
            if not stop.is_set() and not is_paused:
                while next_number <= work_count and len(pending) + len(cooldowns) < workers:
                    if stop.is_set() or not resume.is_set():
                        break
                    if pool is None:
                        pool = ProcessPoolExecutor(max_workers=workers, mp_context=context,
                                                   initializer=initialize_worker, initargs=(stop, resume, results))
                    pending[next_number] = pool.submit(run_work, make_work(next_number))
                    next_number += 1
            try:
                receive(results.get(timeout=0.05))
            except Empty:
                pass
            # 程序異常死亡可能無法發送 finished；不能無限等待佇列。
            for number, future in list(pending.items()):
                if future.done() and future.exception() is not None:
                    error = error or future.exception()
                    stop.set()
                    resume.set()
                    pending.pop(number)
                    active.discard(number)
                    finished_count += 1
            notify()
        # 異常死亡時仍保存已到達協調端的其他結果。
        while True:
            try:
                receive(results.get_nowait())
            except Empty:
                break
        if error:
            raise error
        return stop.is_set()
    finally:
        stop.set()
        resume.set()
        # 保存端失敗也須持續排空，避免子程序堵在有界佇列而無法退出。
        while pending:
            try:
                kind, number, _ = results.get(timeout=0.05)
                if kind == "finished":
                    pending.pop(number, None)
            except Empty:
                pass
            for number, future in list(pending.items()):
                if future.cancelled() or (future.done() and future.exception() is not None):
                    pending.pop(number)
        if pool:
            pool.shutdown(wait=True, cancel_futures=True)
        if bind_control:
            bind_control(None, None)
        results.close()
        results.join_thread()
