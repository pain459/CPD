"""CPD worker autoscaler: grows worker containers with queue load, shrinks when idle.

Policy: load = queued + actively-processing jobs; desired = clamp(load, MIN, MAX).
Scale-up is immediate; scale-down waits for COOLDOWN seconds of zero load and
removes one idle container per loop. Managed containers carry label
cpd.autoscaled=true and are removed on shutdown. State is published to Redis
(cpd:scaler) for /api/health. Local-dev only: needs the Docker socket.
"""
import json
import os
import signal
import sys
import time
import uuid

import docker
import psycopg
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://cpd:cpd_dev_password@postgres:5432/cpd")
PG_DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
QUEUE_KEY = "cpd:queue"
STATE_KEY = "cpd:scaler"

MIN_WORKERS = int(os.getenv("MIN_WORKERS", "1"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))
POLL = int(os.getenv("SCALER_POLL_SECONDS", "3"))
COOLDOWN = int(os.getenv("SCALE_DOWN_COOLDOWN_SECONDS", "30"))
ACTIVE = ("QUEUED", "PARSING", "VALIDATING", "TRANSFORMING", "LOADING")

MANAGED = {"cpd.autoscaled": "true"}
BASE_LABELS = {"com.docker.compose.service": "worker"}

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
stop = False


def on_term(*_a):
    global stop
    stop = True


def base_workers(dcli):
    return [c for c in dcli.containers.list(
        filters={"label": "com.docker.compose.service=worker"}) if c.name and "auto-" not in c.name]


def managed(dcli):
    return dcli.containers.list(filters={"label": "cpd.autoscaled=true"})


def load():
    q = r.llen(QUEUE_KEY)
    with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM etl_jobs WHERE status = ANY(%s)", (list(ACTIVE),))
        active = cur.fetchone()[0]
    return q, active


def clone_from(dcli, template):
    """Build create-kwargs mirroring a running compose worker (image/env/mounts/nets)."""
    a = template.attrs
    vols = {}
    for m in a.get("Mounts", []):
        if m.get("Type") == "volume":
            vols[m["Name"]] = {"bind": m["Destination"], "mode": "rw"}
    return {
        "image": a["Config"]["Image"],
        "environment": list(a["Config"]["Env"]),
        "volumes": vols,
        "network": next(iter(a["NetworkSettings"]["Networks"]), None),
        "labels": MANAGED,
        "detach": True,
    }


def spawn(dcli, template):
    kw = clone_from(dcli, template)
    name = f"cpd-worker-auto-{uuid.uuid4().hex[:8]}"
    c = dcli.containers.create(name=name, hostname=name, **{k: v for k, v in kw.items() if v is not None})
    c.start()
    print(f"scale-up: started {name}", flush=True)
    return c


def retire(container):
    try:
        container.stop(timeout=10)
        container.remove()
        print(f"scale-down: removed {container.name}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"scale-down: {container.name} failed: {e}", flush=True)


def publish(queue, active, desired, actual):
    try:
        r.set(STATE_KEY, json.dumps({"ts": int(time.time()), "queue": queue,
                                     "active": active, "desired": desired,
                                     "actual": actual, "min": MIN_WORKERS, "max": MAX_WORKERS}))
    except Exception as e:  # noqa: BLE001
        print(f"state publish failed: {e}", flush=True)


def main():
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    dcli = docker.from_env()
    idle_since = None
    print(f"scaler up: min={MIN_WORKERS} max={MAX_WORKERS} poll={POLL}s cooldown={COOLDOWN}s", flush=True)
    while not stop:
        try:
            queue, active = load()
            base = base_workers(dcli)
            extra = managed(dcli)
            actual = len(base) + len(extra)
            desired = max(MIN_WORKERS, min(MAX_WORKERS, queue + active))
            if actual < desired:
                template = (base + extra)[0]
                for _ in range(desired - actual):
                    extra.append(spawn(dcli, template))
                    actual += 1
                    time.sleep(2)
                idle_since = None
            elif actual > desired and queue + active == 0:
                if idle_since is None:
                    idle_since = time.time()
                elif time.time() - idle_since >= COOLDOWN and extra:
                    retire(extra[0])
                    idle_since = time.time()  # one per loop at most
            else:
                idle_since = None if queue + active else idle_since
            publish(queue, active, desired, actual)
        except Exception as e:  # noqa: BLE001
            print(f"loop error: {e}", flush=True)
        for _ in range(POLL * 2):
            if stop:
                break
            time.sleep(0.5)
    print("scaler stopping: removing managed workers", flush=True)
    for c in managed(dcli):
        retire(c)


if __name__ == "__main__":
    sys.exit(main())
