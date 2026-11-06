#!/usr/bin/env python3
"""UDP heartbeat listener for the M5 Core2 WiFi status board.

Receives one datagram per Core2 test cycle, e.g.
    tok=SECRET up=1234 g=0 n=0 t=0 bat=87
(g/n/t = Ghorman/Naboo/T-Mobile verdict: 0 green, 1 yellow, 2 red; up = uptime in seconds)
and, if the token matches and the fields are valid, atomically rewrites STATE_DIR/last_seen.
The file's modification time is the "last heartbeat" time; the Zabbix agent reads it on the host.
Standard library only.
"""
import hmac
import os
import socket
import sys
import time

BIND = os.environ.get("BIND_ADDR", "0.0.0.0")
PORT = int(os.environ.get("PORT", "9099"))
STATE_DIR = os.environ.get("STATE_DIR", "/state")
TOKEN = os.environ.get("M5CORE2_TOKEN", "")
FIELDS = ("up", "g", "n", "t", "bat")
MAX_LEN = 256            # datagrams longer than this are ignored
LOG_REJECT_EVERY = 60    # seconds; keeps scanners from filling the log


def parse(data):
    """Return {field: int} if the datagram is well formed and the token matches, else None."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        return None
    kv = {}
    for part in text.split():
        key, sep, value = part.partition("=")
        if not sep:
            return None
        kv[key] = value
    if not hmac.compare_digest(kv.get("tok", "").encode(), TOKEN.encode()):
        return None
    out = {}
    for name in FIELDS:
        value = kv.get(name)
        if value is None or len(value) > 10:
            return None
        try:
            out[name] = int(value)
        except ValueError:
            return None
    return out


def write_state(fields):
    line = " ".join(f"{name}={fields[name]}" for name in FIELDS) + "\n"
    tmp = os.path.join(STATE_DIR, ".last_seen.tmp")
    with open(tmp, "w") as fh:
        fh.write(line)
    os.chmod(tmp, 0o644)  # the Zabbix agent runs as a different user
    os.replace(tmp, os.path.join(STATE_DIR, "last_seen"))


def main():
    if not TOKEN:
        sys.exit("M5CORE2_TOKEN is not set; refusing to run without a token")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((BIND, PORT))
    print(f"listening on {BIND}:{PORT}/udp, state in {STATE_DIR}", flush=True)
    rejected = 0
    last_reject_log = 0.0
    while True:
        try:
            data, addr = sock.recvfrom(MAX_LEN + 1)
        except OSError:  # e.g. Windows raises on an oversize datagram (Linux truncates); treat as junk
            data, addr = b"", ("?",)
            time.sleep(0.1)
        fields = parse(data) if len(data) <= MAX_LEN else None
        if fields is None:
            rejected += 1
            now = time.monotonic()
            if now - last_reject_log >= LOG_REJECT_EVERY:
                print(f"rejected {rejected} datagram(s), latest from {addr[0]}", flush=True)
                rejected, last_reject_log = 0, now
            continue
        try:
            write_state(fields)
        except OSError as exc:
            print(f"cannot write state: {exc}", flush=True)
            continue
        print(f"heartbeat from {addr[0]}: {fields}", flush=True)


if __name__ == "__main__":
    main()
