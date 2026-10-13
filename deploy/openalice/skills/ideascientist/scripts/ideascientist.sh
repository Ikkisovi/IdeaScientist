#!/bin/bash
# IdeaScientist (arXiv 2610.04074) on the workstation, API backbones only.
#
#   ideascientist.sh status
#   ideascientist.sh bridges                       # start any loopback bridge that is not listening
#   ideascientist.sh run --out <dir> [--arms gemini,spark,glm] [-P 6] <problem.txt>...
#   ideascientist.sh judge <astra|glm> <run_dir>...  # rubric judge (see SKILL.md for novelty caveat)
#   ideascientist.sh list <dir>                     # report / candidates / reviewer verdict per run
#
# Runtime (venv, vault DBs, patched harness, logs) lives in $IDEASCIENTIST_HOME.
# Credentials are resolved by the bridges from ~/.pi/agent/models.json; never pass keys here.
set -u
W=${IDEASCIENTIST_HOME:-/mnt/samsung_ssd/openalice-data/ideascientist}
SK=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
UPSTREAM=/mnt/qnap-workstation/literature-library/external/repos/IdeaScientist/scripts
declare -A PORT=([glm]=18317 [glm-eval]=18318 [gemini]=18320 [spark]=18321)
declare -A MODEL=([glm]=z-ai/glm-5.3-flash [gemini]=gemini-3.8-flash-high [spark]=muse-spark-1.3-contributor)

listening() { (exec 3<>/dev/tcp/127.0.0.1/$1) 2>/dev/null; }
die() { echo "$*" >&2; exit 2; }
[ -d "$W/venv" ] || die "runtime $W missing (see SKILL.md 'Rebuilding the runtime')"
mkdir -p "$W/logs"

start_bridge() {  # name port cmd...
  local n=$1 p=$2; shift 2
  if listening $p; then echo "$n :$p up"; return; fi
  (cd "$W" && setsid nohup "$@" > "logs/bridge_$n.log" 2>&1 < /dev/null &)
  sleep 2; listening $p && echo "$n :$p started" || echo "$n :$p FAILED (logs/bridge_$n.log)"
}

case ${1:-} in
status)
  for n in glm glm-eval gemini spark; do listening ${PORT[$n]} && s=up || s=down; echo "bridge $n :${PORT[$n]} $s"; done
  listening 8317 && echo "astra (codex-local) :8317 up" || echo "astra (codex-local) :8317 down"
  echo "--- running harness runs"
  ps -eo pid,etime,args | awk '/run_ideation.py|evaluate.py/ && !/awk/ {
    id=""; m=""; for (i=1;i<=NF;i++) { if ($i=="--problem-id") id=$(i+1); if ($i=="--model") m=$(i+1); if ($i ~ /evaluate.py$/) id="judge " $(i+1) }
    print $1, $2, m, id }'
  ;;
bridges)
  start_bridge glm 18317 python3 -I "$SK/cc_proxy.py" 18317 "$W/cc_proxy_usage.jsonl"
  start_bridge glm-eval 18318 python3 -I "$SK/cc_proxy.py" 18318 "$W/cc_proxy_eval_usage.jsonl" \
    '{"thinking":{"type":"disabled"},"reasoning_effort":"low"}' 4096
  start_bridge gemini 18320 python3 -I "$SK/llm_bridge.py" 18320 "$W/bridge_gemini_usage.jsonl" "$SK/bridge_gemini.json"
  start_bridge spark 18321 python3 -I "$SK/llm_bridge.py" 18321 "$W/bridge_spark_usage.jsonl" "$SK/bridge_spark.json"
  ;;
run)
  shift; arms=gemini,spark; par=6; out=
  while [ $# -gt 0 ]; do case $1 in
    --arms) arms=$2; shift 2;; -P) par=$2; shift 2;; --out) out=$2; shift 2;; *) break;; esac; done
  [ -n "$out" ] && [ $# -gt 0 ] || die "usage: run --out <dir> [--arms a,b] [-P n] <problem.txt>..."
  for a in ${arms//,/ }; do listening ${PORT[$a]} || die "bridge $a down: run '$0 bridges' first"; done
  listening 8317 || die "astra reviewer endpoint :8317 down"
  out=$(readlink -f "$out"); mkdir -p "$out"
  for f in "$@"; do for a in ${arms//,/ }; do echo "$a $(readlink -f "$f")"; done; done |
  W=$W out=$out xargs -P "$par" -L 1 bash -c '
    a=$0; f=$1; id=$(basename "$f" .txt); declare -A P=([glm]=18317 [gemini]=18320 [spark]=18321)
    declare -A M=([glm]=z-ai/glm-5.3-flash [gemini]=gemini-3.8-flash-high [spark]=muse-spark-1.3-contributor)
    cd "$W" && source env.sh
    export IDEASCIENTIST_API_KEY=$(python3 -I -c "import json,os;print(json.load(open(os.path.expanduser(\"~/.pi/agent/models.json\")))[\"providers\"][\"codex-local\"][\"apiKey\"])")
    export IDEASCIENTIST_ROLE_BASE_URL="{\"reviewer\": \"http://127.0.0.1:8317/v1\"}" IDEASCIENTIST_ROLE_MODEL="{\"reviewer\": \"gpt-6-astra\"}"
    mkdir -p "$out/runs_$a"; s=$(date +%s)
    PYTHONPATH=$W/IdeaScientist-patched HF_HUB_OFFLINE=1 IDEASCIENTIST_READER_TOKENIZER=Qwen/Qwen3-Embedding-0.6B \
    IDEASCIENTIST_BASE_URL=http://127.0.0.1:${P[$a]}/v1 IDEASCIENTIST_MODEL=${M[$a]} \
      venv/bin/python "$W/IdeaScientist-patched/scripts/run_ideation.py" --problem-file "$f" --problem-id "$id" --model ${M[$a]} \
        --run-dir "$out/runs_$a" > "$out/runs_$a/$id.log" 2>&1
    echo "$a $id exit=$? wall=$(( $(date +%s)-s ))s"'
  ;;
judge)
  shift; j=${1:-}; shift || true
  cd "$W" && source env.sh
  if [ "$j" = astra ]; then
    M=gpt-6-astra; export IDEASCIENTIST_BASE_URL=http://127.0.0.1:8317/v1; unset IDEASCIENTIST_EXTRA_BODY
    export IDEASCIENTIST_API_KEY=$(python3 -I -c "import json,os;print(json.load(open(os.path.expanduser('~/.pi/agent/models.json')))['providers']['codex-local']['apiKey'])")
  elif [ "$j" = glm ]; then M=$IDEASCIENTIST_MODEL; export IDEASCIENTIST_BASE_URL=$IDEASCIENTIST_EVAL_BASE_URL
  else die "judge must be astra|glm"; fi
  T=${M//\//_}; T=${T##*_}
  for r in "$@"; do
    if [ -f "$r/outputs/completion.json" ]; then
      s=$(venv/bin/python -c "import json,sys;print(json.load(open(sys.argv[1]))['status'])" "$r/outputs/completion.json")
      [ "$s" = proposal_unvalidated ] || { echo "skip $r (completion=$s; no complete proposal to judge)"; continue; }
    fi
    [ -d "$r/evaluation.$T" ] && { echo "skip $r ($M done)"; continue; }
    [ -d "$r/evaluation" ] && { echo "stray evaluation/ in $r; refusing"; continue; }
    s=$(date +%s)
    venv/bin/python $UPSTREAM/evaluate.py "$r" --model "$M" --skip-citations > "$r.eval.$T.log" 2>&1 && mv "$r/evaluation" "$r/evaluation.$T"
    echo "$(basename $r) judge=$M exit=$? wall=$(( $(date +%s)-s ))s"
  done
  ;;
list)
  for d in "${2:?dir}"/runs_*/*/; do
    o=$d/outputs; r=-; [ -s "$o/report.md" ] && r="report $(wc -w < $o/report.md)w"
    c=$(grep -c '^### C[0-9]* verdict' "$o/scores.md" 2>/dev/null || echo 0)
    echo "$(basename $(dirname $d))/$(basename $d)  $r  reviewed_candidates=$c"
  done
  ;;
*) sed -n 2,11p "$0"; exit 2;;
esac
