"""Challenge Drop 3 proof: SOS flood (600 fake requests) while a logged-in dispatcher keeps working.

Run against a server started WITHOUT --reload on a fresh DB:
    rm -f crisis.db*; uvicorn backend.app.main:app --port 8000 &
    python tests/load/flood_test.py --base http://127.0.0.1:8000 --n 600

What it does (all concurrently, via asyncio + httpx):
  * 5 warm-up SOS, then N fake SOS from N random citizen_ids (+ replays of the warm-up payloads -> duplicates);
  * a dispatcher logs in (JWT), triggers one legitimate demo burst (4 citizens -> Red Alert), polls
    /api/dispatch/overview every 100 ms during the flood, and confirms the burst's alert.
Prints accepted / 429 / duplicates / suspected, mean / p95 / max latency, and whether mean < 300 ms.
The fake SOS are fired from --procs client processes (default 6) that all start at the same instant: a single
Python httpx client cannot issue 600 requests at once fast enough and would measure itself, not the server.
Not collected by pytest (tests/conftest.py: collect_ignore).
"""
import argparse
import asyncio
import multiprocessing as mp
import os
import random
import statistics
import time

import httpx

ZONES = [(40.4093, 49.8671), (40.3777, 49.8920), (40.3620, 49.8330), (40.3953, 49.9500), (40.4300, 49.9300)]


def stats(name, lat_ms):
    if not lat_ms:
        return f"{name}: no samples"
    s = sorted(lat_ms)
    p95 = s[min(len(s) - 1, int(0.95 * len(s)))]
    return (f"{name:<22} n={len(s):>4}  mean={statistics.mean(s):7.1f} ms  p95={p95:7.1f} ms  "
            f"max={s[-1]:7.1f} ms")


async def timed(client, method, url, **kw):
    t0 = time.perf_counter()
    try:
        r = await client.request(method, url, **kw)
    except httpx.HTTPError as e:
        return None, (time.perf_counter() - t0) * 1000, e
    return r, (time.perf_counter() - t0) * 1000, None


def fake_body(i, warm):
    if i % 12 == 0:  # replay of an already accepted payload -> duplicate (200, nothing created)
        return warm[i % len(warm)]
    la, lo = random.choice(ZONES)
    return {"lat": la + random.uniform(-0.01, 0.01), "lon": lo + random.uniform(-0.01, 0.01),
            "hazard_type": random.choice(["fire", "collapse", "flood", "medical"]),
            "citizen_id": f"fake-{os.getpid()}-{i}"}


async def _worker(base, idx, warm, start_at):
    limits = httpx.Limits(max_connections=len(idx) + 10)
    async with httpx.AsyncClient(base_url=base, limits=limits, timeout=httpx.Timeout(60.0)) as c:
        bodies = [fake_body(i, warm) for i in idx]
        await asyncio.sleep(max(0.0, start_at - time.time()))

        async def one(body):
            resp, ms, err = await timed(c, "POST", "/api/sos", json=body)
            if err:
                return ms, None, False, repr(err)
            return ms, resp.status_code, resp.status_code == 201 and resp.json().get("suspected_spam"), None

        return await asyncio.gather(*(one(b) for b in bodies))


def worker(args):
    return asyncio.run(_worker(*args))


async def main(base: str, n: int, password: str, procs: int):
    limits = httpx.Limits(max_connections=n + 50, max_keepalive_connections=n + 50)
    async with httpx.AsyncClient(base_url=base, limits=limits, timeout=httpx.Timeout(60.0)) as c:
        r = await c.post("/api/auth/login", json={"username": "dispatcher", "password": password})
        r.raise_for_status()
        staff = {"Authorization": f"Bearer {r.json()['access_token']}"}
        (await c.post("/api/demo/reset", headers=staff)).raise_for_status()

        warm = [{"lat": la, "lon": lo, "hazard_type": "fire", "citizen_id": f"warm-{i}"} for i, (la, lo) in enumerate(ZONES)]
        for body in warm:
            await c.post("/api/sos", json=body)

        sos_lat, codes, errors, suspected = [], {}, [], 0
        done = asyncio.Event()

        ov_lat, ov_codes = [], {}

        async def poll_overview():
            while not done.is_set():
                resp, ms, err = await timed(c, "GET", "/api/dispatch/overview", headers=staff)
                ov_lat.append(ms)
                if resp is not None:
                    ov_codes[resp.status_code] = ov_codes.get(resp.status_code, 0) + 1
                await asyncio.sleep(0.1)

        async def legit_burst():
            await asyncio.sleep(0.05)
            resp, ms, _ = await timed(c, "POST", "/api/demo/sos-burst", headers=staff,
                                      json={"lat": 40.4093, "lon": 49.8671, "count": 4, "hazard_type": "fire"})
            return resp, ms

        start_at = time.time() + 1.5  # all client processes fire at this instant
        chunks = [list(range(k, n, procs)) for k in range(procs)]
        loop = asyncio.get_running_loop()
        with mp.get_context("spawn").Pool(procs) as pool:
            fut = loop.run_in_executor(None, pool.map, worker, [(base, ch, warm, start_at) for ch in chunks])
            await asyncio.sleep(max(0.0, start_at - time.time()))
            t0 = time.perf_counter()
            poller = asyncio.create_task(poll_overview())
            burst_task = asyncio.create_task(legit_burst())
            results = [r for chunk in await fut for r in chunk]
        flood_s = time.perf_counter() - t0
        for ms, code, susp, err in results:
            sos_lat.append(ms)
            if err:
                errors.append(err)
                continue
            codes[code] = codes.get(code, 0) + 1
            suspected += bool(susp)
        burst_resp, burst_ms = await burst_task
        alerts = burst_resp.json()["alerts"] if burst_resp is not None and burst_resp.status_code == 200 else []
        confirm_resp, confirm_ms, _ = (await timed(c, "POST", f"/api/dispatch/alerts/{alerts[0]['id']}/confirm",
                                                   headers=staff)) if alerts else (None, 0.0, None)
        done.set()
        await poller

        ov = (await c.get("/api/dispatch/overview", headers=staff)).json()
        all_lat = sos_lat + ov_lat + [burst_ms] + ([confirm_ms] if confirm_resp is not None else [])
        mean = statistics.mean(all_lat)
        print(f"Flood: {n} fake SOS (+{len(warm)} warm-up) from {procs} client processes on one IP, all fired at "
              f"once; flood phase {flood_s:.2f} s")
        print(f"SOS status codes: {dict(sorted(codes.items()))}  connection errors: {len(errors)}")
        print(f"  accepted (201): {codes.get(201, 0)}  of which suspected_spam: {suspected}")
        print(f"  rate limited (429): {codes.get(429, 0)}  duplicates (200): {codes.get(200, 0)}")
        print(f"Server counters (overview.spam_blocked): {ov['spam_blocked']}")
        print(f"Dispatcher overview polls: {len(ov_lat)}  codes: {ov_codes}  sos_total shown: {ov['sos_total']}")
        print(f"Legit burst: HTTP {burst_resp.status_code if burst_resp is not None else 'ERR'}, "
              f"alerts raised: {len(alerts)}  ({burst_ms:.1f} ms)")
        print(f"Confirm alert: HTTP {confirm_resp.status_code if confirm_resp is not None else 'n/a'} "
              f"({confirm_ms:.1f} ms)")
        open_cluster = [a for a in ov["alerts"] if a["kind"] == "sos_cluster"]
        print(f"Cluster alerts after flood: {len(open_cluster)} (fake SOS raised none: "
              f"{all(set(a['sos_ids']) <= {s['id'] for s in ov['sos']} | set(alerts[0]['sos_ids'] if alerts else []) for a in open_cluster)})")
        print(stats("POST /api/sos", sos_lat))
        print(stats("GET overview", ov_lat))
        print(stats("ALL requests", all_lat))
        print(f"Mean < 300 ms: {'YES' if mean < 300 else 'NO'} ({mean:.1f} ms)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--password", default=os.getenv("DISPATCHER_PASSWORD", "dispatcher123"))
    a = ap.parse_args()
    asyncio.run(main(a.base, a.n, a.password, a.procs))
