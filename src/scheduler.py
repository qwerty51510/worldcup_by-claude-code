"""
排程員：輪詢賽果，偵測到新結果時自動觸發 orchestrator + position_monitor
用法：
  python -m src.scheduler                         # dry-run，每 300s
  python -m src.scheduler --live                  # 真實模式
  python -m src.scheduler --interval 120 --live  # 每 2 分鐘輪詢
"""

import argparse
import json
import time
from pathlib import Path


def _load_result_ids(results_file: Path) -> set[str]:
    if not results_file.exists():
        return set()
    try:
        data = json.loads(results_file.read_text())
        # 以 (date + home_team + away_team) 做唯一鍵，兼容無 match_id 的格式
        ids = set()
        for r in data:
            key = f"{r.get('date','')}/{r.get('home_team','')}/{r.get('away_team','')}"
            ids.add(key)
        return ids
    except Exception:
        return set()


def run(live: bool = False, interval: int = 300) -> None:
    from src.orchestrator      import run as orchestrate
    from src.position_monitor  import check_and_execute as monitor

    results_file = Path("data/wc2026_results.json")
    seen = _load_result_ids(results_file)
    mode = "⚡ LIVE" if live else "🔵 DRY RUN"
    print(f"排程員啟動  {mode}  輪詢間隔 {interval}s  已知賽果 {len(seen)} 場")
    print("Ctrl-C 停止\n")

    while True:
        try:
            current = _load_result_ids(results_file)
            new_results = current - seen

            if new_results:
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] 偵測到 {len(new_results)} 場新賽果 → 觸發分析")

                # 1. 先檢查現有持倉是否需要調整
                monitor_logs = monitor(dry_run=not live)
                for line in monitor_logs:
                    print(f"  [monitor] {line}")

                # 2. 重新掃描機會並（可選）下單
                orchestrate(dry_run=not live)
                seen = current
            else:
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] 無新賽果，{interval}s 後再檢查")

        except KeyboardInterrupt:
            print("\n排程員已停止")
            break
        except Exception as e:
            print(f"[排程員] 錯誤：{e}")

        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",     action="store_true",  help="真實模式")
    parser.add_argument("--interval", type=int, default=300, help="輪詢間隔（秒）")
    args = parser.parse_args()
    run(live=args.live, interval=args.interval)
