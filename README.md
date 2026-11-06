# m5-core2-chk

Lets Zabbix alert you when an [M5Stack Core2](https://docs.m5stack.com/en/core/core2) WiFi status board stops working.

The Core2 sends one tiny UDP datagram (about 60 bytes, roughly every 2.5 minutes) to a small Docker container on a
Linux box. The container records when it last heard from the Core2. A Zabbix agent on the same box reads that record
through `UserParameter` keys. Zabbix polls the agent, so nothing is pushed into Zabbix and the Core2 only needs to
reach one LAN address.

```
Core2 --UDP 9099--> container --writes--> state/last_seen <--reads-- m5core2_check.sh <-- zabbix agent <-- Zabbix
```

This is the receiving half. The Core2 firmware lives in the companion repository
[Core2](https://github.com/jkozik/Core2) (the sender is `sendHeartbeat()` in its `src/main.cpp`).

## What you get

Zabbix items (type *Zabbix agent (active)*) on the host that runs this:

| Key | Meaning |
|---|---|
| `m5core2.health[420]` | 1 = heard from the Core2 within 420 s, 0 = silent (the main alert) |
| `m5core2.heartbeat.age` | Seconds since the last heartbeat |
| `m5core2.field[g]` `[n]` `[t]` | Last reported status of each monitored network: 0 green, 1 yellow, 2 red, 3 unknown |
| `m5core2.field[bat]` | Core2 battery, % |
| `m5core2.field[up]` | Core2 uptime, seconds |

Suggested trigger: `last(/HOST/m5core2.health[420])=0`. The Core2 heartbeats about every 142 s, so 420 s tolerates one
missed heartbeat.

## Requirements

- Linux host with Docker and Docker Compose, and a classic Zabbix agent (`zabbix_agentd`)
- The Core2 and the host on the same LAN

## Setup

1. Copy this folder to the host, e.g. `~/projects/m5-core2-chk`.
2. Create the settings file and lock it down:
   ```
   cp .env.example .env && chmod 600 .env
   ```
   Set `M5CORE2_TOKEN` to a random string (`openssl rand -hex 8`) and `BIND_IP` to the host's LAN address.
   Put the same token and address in the Core2's `include/secrets.h`.
3. Start it:
   ```
   docker compose up -d --build
   ```
4. Edit the paths in `m5core2.conf` if you did not use `~/projects/m5-core2-chk`, then install it and restart the agent:
   ```
   sudo cp m5core2.conf /etc/zabbix/zabbix_agentd.conf.d/
   sudo systemctl restart zabbix-agent
   ```
5. In Zabbix, add the items above to the host and create the trigger. Optionally add a value mapping for the status
   items (0 OK, 1 Degraded, 2 Down, 3 Unknown).

## Check it

```
docker logs m5core2-heartbeat                 # "heartbeat from <core2 ip>: {...}"
./m5core2_check.sh age                        # seconds since last heartbeat
./m5core2_check.sh health                     # 1 or 0
zabbix_agentd -t 'm5core2.health[420]'        # what the agent will report
```

## Files

| File | Purpose |
|---|---|
| `listener.py` | UDP listener, standard library only |
| `Dockerfile`, `.dockerignore` | Small image (`python:3.13-alpine`, about 46 MB) |
| `docker-compose.yml` | Runs it |
| `m5core2_check.sh` | What the agent runs: `age`, `health [max]`, `field NAME` |
| `m5core2.conf` | The `UserParameter` lines |
| `.env.example` | Template for `.env` (token and bind address; `.env` is not committed) |
| `state/` | Runtime data (not committed) |

## Security and footprint

- Datagrams without the right token are dropped (logged at most once a minute). The token is not encryption: this is
  meant for a trusted LAN, and the port is published on the LAN address only.
- Container: non-root, read-only filesystem, all capabilities dropped, `no-new-privileges`, 32 MB memory cap, 16 process
  cap. Typical use is about 7 MiB and near-zero CPU.
- Only `.env` holds a secret, and it is git-ignored.
