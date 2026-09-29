#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
if [[ "$MODE" != "--formal" && "$MODE" != "--smoke" ]]; then
  echo "Usage: $0 --smoke | --formal"
  exit 2
fi

BROKER="172.16.10.200"
SUB_HOST="ogawa@172.16.10.210"
ROOT="$HOME/aomqtt-client-sdk-v1.3.7"
EXPECTED="6dc0b2c497098aca569a636d1f8f8bb2adc4253a"
ARCHIVE_BASE="$HOME/aomqtt-experiment-archives"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ "$MODE" == "--formal" ]]; then
  RUNSET="e1-v137-replication-${STAMP}"
  COUNT=6000
else
  RUNSET="e1-v137-smoke-${STAMP}"
  COUNT=100
fi
OUT="$ARCHIVE_BASE/$RUNSET"
REMOTE_BASE="$HOME/aomqtt-e1-v137-work/$RUNSET"
INTERVAL="0.01"
QOS="1"

pick_python() {
  for p in "$ROOT/.venv/bin/python" "$HOME/aomqtt-client-sdk-v1.3.5/.venv/bin/python" python3; do
    if [[ -x "$p" ]] || command -v "$p" >/dev/null 2>&1; then echo "$p"; return 0; fi
  done
  return 1
}
PY="$(pick_python)"

echo "===== B-8 E1 v1.3.7 replication ====="
echo "mode=$MODE"
echo "runset=$RUNSET"
echo "out=$OUT"
echo "python=$PY"

mkdir -p "$OUT"
cp "$HOME/b8_plain_publisher.py" "$OUT/"
cp "$HOME/b8_plain_subscriber.py" "$OUT/"
cp "$HOME/b8_e1_v137_analyze.py" "$OUT/"
cp "$HOME/b8_e1_v137_formal_runner.sh" "$OUT/"

preflight_local() {
  cd "$ROOT"
  [[ "$(git rev-parse HEAD)" == "$EXPECTED" ]] || { echo "publisher commit mismatch"; exit 1; }
  [[ -z "$(git status --porcelain)" ]] || { echo "publisher v1.3.7 tree is dirty; refusing"; git status --short; exit 1; }
  PYTHONPATH="$ROOT" "$PY" - <<'PY'
import aomqtt, pathlib
print("aomqtt_import=", pathlib.Path(aomqtt.__file__).resolve())
PY
  grep -Eq '^[[:space:]]*token_hex_len:[[:space:]]*16' examples/config.example.yaml \
    || { echo "token_hex_len != 16 or not found"; exit 1; }
}

preflight_remote() {
  ssh "$SUB_HOST" "set -e;
    ROOT=\$HOME/aomqtt-client-sdk-v1.3.7;
    cd \$ROOT;
    test \"\$(git rev-parse HEAD)\" = '$EXPECTED';
    test -z \"\$(git status --porcelain)\";
    PY=\$HOME/aomqtt-client-sdk-v1.3.5/.venv/bin/python;
    test -x \$PY || PY=python3;
    PYTHONPATH=\$ROOT \$PY -c 'import aomqtt,pathlib; print(pathlib.Path(aomqtt.__file__).resolve())';
    grep -Eq '^[[:space:]]*token_hex_len:[[:space:]]*16' examples/config.example.yaml;
    mkdir -p '$REMOTE_BASE'"
}

preflight_local
preflight_remote

# Copy the plain subscriber helper to subscriber-1.
scp -q "$HOME/b8_plain_subscriber.py" "$SUB_HOST:$REMOTE_BASE/plain_subscriber.py"

# Record provenance.
{
  echo "runset=$RUNSET"
  echo "mode=$MODE"
  echo "publisher_host=$(hostname)"
  echo "publisher_repo=$ROOT"
  echo "publisher_commit=$(cd "$ROOT" && git rev-parse HEAD)"
  echo "publisher_tag=$(cd "$ROOT" && git describe --tags --exact-match HEAD 2>/dev/null || true)"
  echo "python=$("$PY" --version 2>&1)"
  echo "broker=$BROKER:1883"
  echo "subscriber_host=$SUB_HOST"
  echo "token_mode=hierarchical"
  echo "pacing=post-sleep"
  echo "count=$COUNT"
  echo "interval=$INTERVAL"
  echo "qos=$QOS"
  echo "a4_rotation_interval=30"
  echo "a4_rotation_overlap=5"
  echo "a4_start_phase_target=9"
} > "$OUT/provenance.txt"
cd "$ROOT"
git show HEAD:examples/config.example.yaml > "$OUT/v137-config.example.yaml"
git diff --exit-code > "$OUT/v137-working-tree.diff" || true
"$PY" -m pip freeze > "$OUT/pip-freeze-publisher.txt" 2>/dev/null || true
chronyc tracking > "$OUT/chrony-runset-start.txt" 2>&1 || true
chronyc sources -v >> "$OUT/chrony-runset-start.txt" 2>&1 || true

remote_py='
ROOT=$HOME/aomqtt-client-sdk-v1.3.7
if test -x "$ROOT/.venv/bin/python"; then PY="$ROOT/.venv/bin/python";
elif test -x "$HOME/aomqtt-client-sdk-v1.3.5/.venv/bin/python"; then PY="$HOME/aomqtt-client-sdk-v1.3.5/.venv/bin/python";
else PY=python3; fi
'

start_subscriber() {
  local cond="$1" rep="$2" topic="$3" rid="$4"
  local rdir="$REMOTE_BASE/$rid"
  ssh "$SUB_HOST" "set -e; mkdir -p '$rdir'; chronyc tracking > '$rdir/chrony-before.txt' 2>&1 || true; chronyc sources -v >> '$rdir/chrony-before.txt' 2>&1 || true"
  if [[ "$cond" == "A1" ]]; then
    ssh "$SUB_HOST" "set -e; $remote_py
      nohup \$PY '$REMOTE_BASE/plain_subscriber.py' \
        --broker '$BROKER' --port 1883 --topic '$topic' --count '$COUNT' --qos '$QOS' \
        --client-id '${rid}-sub' --metrics-csv '$rdir/subscriber_metrics.csv' --timeout 120 \
        > '$rdir/subscriber.log' 2>&1 < /dev/null &
      echo \$! > '$rdir/subscriber.pid'"
  else
    local rot="--no-rotation"
    [[ "$cond" == "A4" ]] && rot="--rotation --rotation-interval 30 --rotation-overlap 5"
    ssh "$SUB_HOST" "set -e; $remote_py
      cd \$ROOT
      nohup env PYTHONUNBUFFERED=1 PYTHONPATH=\$ROOT \$PY examples/subscriber_example.py \
        --broker '$BROKER' --port 1883 --config examples/config.example.yaml \
        --topic '$topic' --qos '$QOS' --token-mode hierarchical $rot \
        --delivery-csv '$rdir/subscriber_metrics.csv' \
        --experiment-id e1-v137-replication --run-id '$rid' \
        --save-experiment-config --experiment-config-out '$rdir/subscriber_experiment_config.json' \
        > '$rdir/subscriber.log' 2>&1 < /dev/null &
      echo \$! > '$rdir/subscriber.pid'"
  fi
  # Give SUBSCRIBE time to reach the broker.
  sleep 2
}

stop_subscriber() {
  local rid="$1" rdir="$REMOTE_BASE/$rid"
  # Plain subscriber normally exits by itself. AOMQTT example is stopped gracefully.
  ssh "$SUB_HOST" "set +e;
    if test -f '$rdir/subscriber.pid'; then
      pid=\$(cat '$rdir/subscriber.pid');
      if kill -0 \$pid 2>/dev/null; then kill -INT \$pid 2>/dev/null; fi;
      for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 \$pid 2>/dev/null || break; sleep .5; done;
      kill -0 \$pid 2>/dev/null && kill -TERM \$pid 2>/dev/null;
    fi;
    chronyc tracking > '$rdir/chrony-after.txt' 2>&1 || true;
    chronyc sources -v >> '$rdir/chrony-after.txt' 2>&1 || true"
}

wait_phase9() {
  "$PY" - <<'PY'
import time
while True:
    p=time.time()%30
    if 8.95 <= p < 9.05:
        print(f"phase_gate={p:.6f}", flush=True)
        break
    time.sleep(0.01)
PY
}

run_one() {
  local cond="$1" rep="$2"
  local lc="${cond,,}"
  local rid="formal-${lc}-r$(printf '%02d' "$rep")"
  local topic="iot-formal/${lc}/r$(printf '%02d' "$rep")"
  local d="$OUT/$rid"
  mkdir -p "$d"
  echo
  echo "===== $rid ====="
  chronyc tracking > "$d/chrony-before-publisher.txt" 2>&1 || true
  chronyc sources -v >> "$d/chrony-before-publisher.txt" 2>&1 || true

  start_subscriber "$cond" "$rep" "$topic" "$rid"

  if [[ "$cond" == "A4" && "$MODE" == "--formal" ]]; then
    wait_phase9 | tee "$d/phase-gate.txt"
    "$PY" - <<'PY' > "$d/rotation_start.txt"
import time, datetime
t=time.time()
print("start_time_utc="+datetime.datetime.fromtimestamp(t,datetime.timezone.utc).isoformat())
print(f"start_epoch={t:.9f}")
print(f"start_phase={t%30:.6f}")
PY
  fi

  if [[ "$cond" == "A1" ]]; then
    "$PY" "$HOME/b8_plain_publisher.py" \
      --broker "$BROKER" --port 1883 --topic "$topic" --count "$COUNT" --interval "$INTERVAL" --qos "$QOS" \
      --client-id "${rid}-pub" --metrics-csv "$d/publisher_metrics.csv" \
      > "$d/publisher.log" 2>&1
  else
    cd "$ROOT"
    local rot="--no-rotation"
    local pad="--padding-mode none"
    [[ "$cond" == "A3" ]] && pad="--padding-mode fixed --padding-fixed-size 512"
    if [[ "$cond" == "A4" ]]; then
      rot="--rotation --rotation-interval 30 --rotation-overlap 5"
      pad="--padding-mode fixed --padding-fixed-size 512"
    fi
    env PYTHONPATH="$ROOT" "$PY" examples/publisher_example.py \
      --broker "$BROKER" --port 1883 --config examples/config.example.yaml \
      --topic "$topic" --count "$COUNT" --interval "$INTERVAL" --pacing post-sleep --qos "$QOS" \
      --token-mode hierarchical $rot $pad \
      --metrics-csv "$d/publisher_metrics.csv" \
      --experiment-id e1-v137-replication --run-id "$rid" \
      --save-experiment-config --experiment-config-out "$d/publisher_experiment_config.json" \
      > "$d/publisher.log" 2>&1
  fi

  sleep 3
  stop_subscriber "$rid"
  scp -q "$SUB_HOST:$REMOTE_BASE/$rid/subscriber_metrics.csv" "$d/" || true
  scp -q "$SUB_HOST:$REMOTE_BASE/$rid/subscriber.log" "$d/" || true
  scp -q "$SUB_HOST:$REMOTE_BASE/$rid/subscriber_experiment_config.json" "$d/" 2>/dev/null || true
  scp -q "$SUB_HOST:$REMOTE_BASE/$rid/chrony-before.txt" "$d/chrony-before-subscriber.txt" || true
  scp -q "$SUB_HOST:$REMOTE_BASE/$rid/chrony-after.txt" "$d/chrony-after-subscriber.txt" || true
  chronyc tracking > "$d/chrony-after-publisher.txt" 2>&1 || true
  chronyc sources -v >> "$d/chrony-after-publisher.txt" 2>&1 || true

  # Fast structural gate.
  "$PY" - "$d" "$cond" "$COUNT" <<'PY'
import csv,sys,pathlib
d=pathlib.Path(sys.argv[1]); c=sys.argv[2]; n=int(sys.argv[3])
def rows(p):
    with p.open(newline="") as f:return list(csv.DictReader(f))
pub=rows(d/"publisher_metrics.csv"); sub=rows(d/"subscriber_metrics.csv")
if c=="A1":
    u={r["seq"] for r in pub}
    su={r["seq"] for r in sub if r.get("seq","")!=""}
else:
    u={r["logical_seq"] for r in pub if r.get("logical_seq","")!=""}
    su={r["logical_seq"] for r in sub if r.get("logical_seq","")!="" and str(r.get("decrypt_success","")).lower() in ("1","true","yes")}
print(f"gate condition={c} publisher_rows={len(pub)} pub_unique={len(u)} subscriber_rows={len(sub)} sub_unique={len(su)}")
if len(u)!=n or len(su)!=n:
    raise SystemExit("STRUCTURAL_GATE_FAIL")
PY
  echo "$rid PASS"
}

if [[ "$MODE" == "--smoke" ]]; then
  run_one A1 1
  run_one A2 1
  run_one A3 1
  run_one A4 1
else
  # Reproduce the historical E1 condition-order pattern inferred from formal timestamps.
  run_one A1 1; run_one A2 1; run_one A3 1; run_one A4 1
  run_one A2 2; run_one A3 2; run_one A4 2; run_one A1 2
  run_one A3 3; run_one A4 3; run_one A1 3; run_one A2 3
  run_one A4 4; run_one A1 4; run_one A2 4; run_one A3 4
  run_one A4 5; run_one A3 5; run_one A2 5; run_one A1 5
fi

chronyc tracking > "$OUT/chrony-runset-end.txt" 2>&1 || true
chronyc sources -v >> "$OUT/chrony-runset-end.txt" 2>&1 || true

if [[ "$MODE" == "--formal" ]]; then
  "$PY" "$HOME/b8_e1_v137_analyze.py" "$OUT" | tee "$OUT/analysis.log"
fi

(
  cd "$OUT"
  find . -type f ! -name SHA256SUMS.txt -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS.txt
)
TAR="$ARCHIVE_BASE/${RUNSET}.tar.gz"
tar -C "$ARCHIVE_BASE" -czf "$TAR" "$RUNSET"
sha256sum "$TAR" | tee "${TAR}.sha256"

echo
echo "RUNSET=$RUNSET"
echo "OUT=$OUT"
echo "TAR=$TAR"
echo "B8_E1_V137_REPLICATION_COMPLETE"
