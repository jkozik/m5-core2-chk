# Notes: how m5-core2-chk was built

A record of the steps and decisions, so future me can maintain or rebuild it. Usage is in `README.md`.

## Goal

Zabbix should alert when the M5 Core2 WiFi status board stops working, with a minimal footprint on the Core2, the
network and the host. The Core2 rotates between three SSIDs, so it cannot be pinged reliably (and it does not answer
ping anyway: 0 of 25 replies were seen).

## Environment

- Host: Debian 13 TinyPC `osprey`, ~1.4 GB RAM free, classic `zabbix-agent` (active mode), Docker with compose.
- Zabbix 7.4 server is remote. A separate Zabbix proxy container on the same host polls IoT devices; it is not involved
  here. The agent on osprey talks to the server directly.
- Existing agent config uses one file per feature in `/etc/zabbix/zabbix_agentd.conf.d/`; this project follows that.

## Design decisions

1. **Heartbeat, not ping.** The Core2 sends a UDP datagram while it is connected to the Ghorman (primary) network, the
   one the host is on. The device is on other SSIDs part of each cycle, so only a deliberate send is meaningful.
2. **Zabbix polls.** Server-side preference: no pushes into Zabbix, so no trapper ports, API tokens or server
   addresses on the device. The agent runs a script that reads local state.
3. **Items on the existing host `osprey`**, not a separate Core2 host. The thing being monitored is the listener's view
   of the Core2, and the Core2 has no agent.
4. **Docker container, not systemd.** Preferred for trackability. Kept proportional: `python:3.13-alpine`, stdlib only,
   one file copied in, 45.7 MB image, about 7 MiB RAM.
5. **Token auth.** A shared random token in each datagram, compared with `hmac.compare_digest`. Not encryption; fine for
   a trusted LAN.
6. **State is a file's mtime.** The listener atomically rewrites `state/last_seen` (temp file plus `os.replace`). The
   check script reads the file's age, so it works even if the container is down (age grows, health goes to 0).
7. **Health = 1 means OK.** Age at most 420 s. Measured heartbeat spacing is ~142 s (22 s test cycle plus a 120 s wait),
   so an initial threshold of 300 s was too tight and was raised to 420 s (tolerates one missed beat).
8. **Wire format:** `tok=<token> up=<s> g=<v> n=<v> t=<v> bat=<%>`. Status values: 0 green, 1 yellow, 2 red, 3 unknown.
   Naboo = 1 means failover (its traffic is leaving via T-Mobile). The Core2 sends two copies 250 ms apart, since UDP
   is unacknowledged.

## Steps followed

1. Inspected osprey read-only over SSH: agent type, config directory, existing `UserParameter` files, Docker and the
   proxy's compose file, memory.
2. Chose the design above and agreed names: project folder `~/projects/m5-core2-chk` (the repo checks the Core2), Zabbix
   item "Core2 Health Test".
3. Wrote the listener, Dockerfile, compose file, check script, agent conf, `.env.example` and `.gitignore` in the
   Core2 workspace (`osprey/`), then deployed the folder to osprey.
4. Tested the listener and parser on the laptop first, including oversized and malformed datagrams. This found that a
   too-large datagram raised a socket error on Windows and killed the listener; `recvfrom` is now wrapped in
   `try/except OSError`.
5. Created `.env` on osprey (mode 600) with a random token and `BIND_IP`. Confirmed the token equals the one in the
   Core2 firmware by comparing hashes, never printing it.
6. Flashed the Core2 with heartbeat firmware (the first attempt failed because the device was unplugged; replug and
   retry).
7. `docker compose up -d --build`. Verified end to end: Core2 serial `[heartbeat] sent`; container log
   `heartbeat from <core2>: {...}`; `state/last_seen` updated; `m5core2_check.sh health` returned 1.
8. Installed `m5core2.conf` into `/etc/zabbix/zabbix_agentd.conf.d/` as root and restarted the agent. Verified with
   `zabbix_agentd -t` for each key.
9. In Zabbix, created items on host `osprey` and then triggers. A trigger can only use an item that already exists on
   the host: creating the trigger for `m5core2.field[g]` first gave "Incorrect item key ... provided for trigger
   expression". Create the item, then the trigger.
10. Added value mappings (0 OK, 1 Degraded, 2 Down, 3 Unknown; separate 1 OK / 0 lost mapping for health). Latest Data
    shows all items reporting.

## Zabbix configuration (on the server)

Items on host `osprey`, type *Zabbix agent (active)*, interval 1m:

| Item | Key | Type |
|---|---|---|
| Core2 Health Test | `m5core2.health[420]` | Numeric (unsigned) |
| Core2 heartbeat age | `m5core2.heartbeat.age` | Numeric (unsigned), units `s` |
| Core2 Ghorman / Naboo / T-Mobile status | `m5core2.field[g]` `[n]` `[t]` | Numeric (unsigned) with value mapping |
| Core2 battery | `m5core2.field[bat]` | Numeric (unsigned), units `%` |

Triggers: `health[420]=0` (Core2 not reporting), `field[g]=2` (Ghorman down), `field[t]=2` (T-Mobile gateway down),
`field[n]=1` (Naboo on failover).

## How to

- **Change the stale threshold:** the number in the key is the threshold. Change `m5core2.health[420]` in the Zabbix
  item and trigger; no agent change needed.
- **Rotate the token:** new value in `.env` and in the Core2's `include/secrets.h`, then
  `docker compose up -d` and reflash the Core2.
- **Move the host or change its IP:** update `BIND_IP` in `.env`, `HEARTBEAT_HOST` in the Core2 `secrets.h`, reflash.
- **Move the project folder:** update the three paths in `m5core2.conf`, reinstall it, restart the agent (or set
  `M5CORE2_STATE`).
- **Add a field:** the Core2 sends it as a numeric `key=value`; add the key to `FIELDS` in `listener.py` (and to the
  allowed names in `m5core2_check.sh`, if it restricts them), rebuild, then use `m5core2_check.sh field <key>`.
- **Rebuild after editing:** `docker compose up -d --build`.
- **Debug "Core2 silent":** `docker logs m5core2-heartbeat` (is it receiving?), `./m5core2_check.sh age`, Core2 serial
  output for `[heartbeat] sent|FAILED`, and confirm the Core2 reached Ghorman that cycle.

## Gotchas

- The Core2 only sends while on Ghorman, so a Ghorman outage also silences the heartbeat. The "Core2 not reporting"
  alert therefore also fires in a fiber outage. That is acceptable (the Ghorman red alert and the silence agree), but
  it means the Core2 cannot report a fiber outage over this path.
- UDP is fire and forget. A single lost datagram is tolerated by the threshold.
- Rejected datagrams are logged at most once a minute so a scanner cannot flood the logs.

## Status and ideas

Running since 2026-11-01; all items verified. Left to sit and observe.

Possible later work:
- A container health check (the listener touches an alive file; Docker checks its age).
- Tighter resource limits (e.g. `cpus: 0.25`, memory reservation near the observed ~7 MiB).
- A live failover test with Ghorman unplugged.
