#!/usr/bin/env bash
# 變異測試：以 cosmic-ray 對核心模組逐一植入 mutant（改寫運算子、移除 decorator…），檢驗測試套件能否察覺。
#
# 用法：scripts/mutation/run.sh [平行 worker 數，預設為 CPU 核心數]
# 需求：pip install cosmic-ray；PostgreSQL 可連線（與 manage.py test 相同）
# 結果：.mutation/session.sqlite 與 .mutation/report.html；
#       存活的 mutant 可用 cr-report --surviving-only --show-diff .mutation/session.sqlite 檢視
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/.mutation"
JOBS="${1:-$(nproc)}"
BASE_PORT=9870

cd "$ROOT"
rm -rf "$OUT"
mkdir -p "$OUT/workers"
export DJANGO_SETTINGS_MODULE=scripts.mutation.settings

worker_pids=()
trap 'kill "${worker_pids[@]}" 2>/dev/null || true' EXIT

# 每個 worker 在獨立的 repo 副本中改寫原始碼，並使用獨立的測試資料庫
urls=()
for i in $(seq 1 "$JOBS"); do
    dir="$OUT/workers/$i"
    mkdir -p "$dir"
    git ls-files -co --exclude-standard | tar -cf - -T - | tar -xf - -C "$dir"

    echo "worker $i：建立測試資料庫並確認基準線全綠..."
    (cd "$dir" && MUTATION_TEST_DB="test_mutation_$i" python manage.py test --keepdb --noinput --failfast >"$OUT/workers/$i.baseline.log" 2>&1) || {
        echo "worker $i 的基準線測試失敗，見 $OUT/workers/$i.baseline.log" >&2
        exit 1
    }

    port=$((BASE_PORT + i))
    (cd "$dir" && MUTATION_TEST_DB="test_mutation_$i" exec cosmic-ray http-worker --port "$port") >"$OUT/workers/$i.log" 2>&1 &
    worker_pids+=($!)
    urls+=("\"http://localhost:$port\"")
done

for i in $(seq 1 "$JOBS"); do
    until curl -s -o /dev/null "http://localhost:$((BASE_PORT + i))"; do sleep 0.2; done
done

{
    cat scripts/mutation/cosmic-ray.toml
    printf '\n[cosmic-ray.distributor.http]\nworker-urls = [%s]\n' "$(IFS=,; echo "${urls[*]}")"
} >"$OUT/config.toml"

cosmic-ray init "$OUT/config.toml" "$OUT/session.sqlite"
cr-filter-operators "$OUT/session.sqlite" "$OUT/config.toml"
cosmic-ray exec "$OUT/config.toml" "$OUT/session.sqlite"

cr-html "$OUT/session.sqlite" >"$OUT/report.html"
cr-report "$OUT/session.sqlite" | tail -n 3
echo "HTML 報告：$OUT/report.html"
