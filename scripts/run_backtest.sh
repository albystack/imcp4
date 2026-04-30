#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROUND="${1:-3}"
DAY_SPEC="${2:-$ROUND}"
TRADER_FILE="${ROOT_DIR}/round_${ROUND}/submission/trader.py"
DATA_DIR="${ROOT_DIR}/backtester_resources"
ROUND_DATA_DIR="${DATA_DIR}/round${ROUND}"
OUT_DIR="${ROOT_DIR}/round_${ROUND}/analysed/backtests"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SAFE_DAY_SPEC="$(printf '%s' "${DAY_SPEC}" | tr -c '[:alnum:]-' '_')"
OUT_FILE="${OUT_DIR}/backtest_round${ROUND}_${SAFE_DAY_SPEC}_${TIMESTAMP}.log"

if [[ $# -gt 2 ]]; then
  EXTRA_ARGS=("${@:3}")
else
  EXTRA_ARGS=()
fi

OPEN_VIS=true
FILTERED_EXTRA_ARGS=()
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  for arg in "${EXTRA_ARGS[@]}"; do
    if [[ "${arg}" == "--no-vis" ]]; then
      OPEN_VIS=false
    else
      FILTERED_EXTRA_ARGS+=("${arg}")
    fi
  done
fi
EXTRA_ARGS=()
if [[ ${#FILTERED_EXTRA_ARGS[@]} -gt 0 ]]; then
  EXTRA_ARGS=("${FILTERED_EXTRA_ARGS[@]}")
fi

DEFAULT_LIMIT_ARGS=()
if [[ "${ROUND}" == "3" || "${ROUND}" == "4" ]]; then
  DEFAULT_LIMIT_ARGS=(
    --limit HYDROGEL_PACK:200
    --limit VELVETFRUIT_EXTRACT:200
    --limit VEV_4000:300
    --limit VEV_4500:300
    --limit VEV_5000:300
    --limit VEV_5100:300
    --limit VEV_5200:300
    --limit VEV_5300:300
    --limit VEV_5400:300
    --limit VEV_5500:300
    --limit VEV_6000:300
    --limit VEV_6500:300
  )
fi

if [[ ! -f "${ROOT_DIR}/.venv/bin/activate" ]]; then
  echo "Missing virtualenv at ${ROOT_DIR}/.venv"
  echo "Create it first with:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -e ./tools/prosperity4bt"
  exit 1
fi

if [[ ! -f "${TRADER_FILE}" ]]; then
  echo "Trader file not found: ${TRADER_FILE}"
  echo "Create round_${ROUND}/submission/trader.py first."
  exit 1
fi

if [[ ! -d "${ROUND_DATA_DIR}" ]]; then
  echo "Round data directory not found: ${ROUND_DATA_DIR}"
  exit 1
fi

if ! find "${ROUND_DATA_DIR}" -maxdepth 1 -type f | grep -q .; then
  echo "No CSV files found in ${ROUND_DATA_DIR}"
  echo "Expected files like prices_round_${ROUND}_day_0.csv and trades_round_${ROUND}_day_0.csv"
  exit 1
fi

mkdir -p "${OUT_DIR}"

# shellcheck disable=SC1091
source "${ROOT_DIR}/.venv/bin/activate"
export PYTHONPATH="${ROOT_DIR}/tools/prosperity4bt:${PYTHONPATH:-}"

echo "Running backtest"
echo "  round:      ${ROUND}"
echo "  day spec:   ${DAY_SPEC}"
echo "  trader:     ${TRADER_FILE}"
echo "  data root:  ${DATA_DIR}"
echo "  output log: ${OUT_FILE}"
echo "  visualizer: ${OPEN_VIS}"

COMMAND=(
  prosperity4btest
  "${TRADER_FILE}"
  "${DAY_SPEC}"
  --data "${DATA_DIR}"
  --out "${OUT_FILE}"
)

if [[ "${OPEN_VIS}" == "true" ]]; then
  COMMAND+=(--vis)
fi

if [[ ${#DEFAULT_LIMIT_ARGS[@]} -gt 0 ]]; then
  COMMAND+=("${DEFAULT_LIMIT_ARGS[@]}")
fi

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  COMMAND+=("${EXTRA_ARGS[@]}")
fi

"${COMMAND[@]}"

echo
echo "Saved log to ${OUT_FILE}"
