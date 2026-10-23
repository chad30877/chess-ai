"""唯讀核對 GitHub 與本機工作票驗收；不代替驗收證據或修改 issue。"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def acceptance_items(body):
    """只讀驗收區塊，避免把其他段落的待辦當成交付條件。"""
    section = re.search(
        r"^##\s+(?:驗收條件|Acceptance criteria)\s*\n(.*?)(?=^##\s|\Z)",
        body.replace("\r\n", "\n"), re.MULTILINE | re.DOTALL,
    )
    if section is None:
        return []
    return [(mark.lower() == "x", text.strip()) for mark, text in re.findall(
        r"^\s*[-*] \[([ xX])\] (.+)$", section.group(1), re.MULTILINE,
    )]


def check_ticket(local_body, remote, phase="audit"):
    if phase == "audit" and remote["state"] != "CLOSED":
        return []
    errors = []
    if phase == "after-close" and remote["state"] != "CLOSED":
        errors.append("GitHub 尚未關閉，結案同步未完成")
    local = acceptance_items(local_body)
    live = acceptance_items(remote["body"])
    for name, items in (("本機", local), ("GitHub", live)):
        if not items:
            errors.append(f"{name}缺少可核對的驗收條件")
        for done, text in items:
            if not done:
                errors.append(f"{name}驗收未完成：{text}")
    if local != live:
        errors.append("本機與 GitHub 的驗收內容或勾選狀態不一致")
    return errors


def inspect_tickets(manifest_path, issue, phase, fetch):
    """發布索引只用於定位票，不把發布時雜湊視為目前進度。"""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tickets = manifest["tickets"]
    selected = [ticket for ticket in tickets if issue is None or ticket["number"] == issue]
    if not selected:
        raise ValueError("發布索引沒有指定工作票；不檢查父規格")
    errors = []
    for ticket in selected:
        path = (manifest_path.parent / ticket["file"]).resolve()
        if not path.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError("工作票路徑超出發布索引目錄")
        local = path.read_text(encoding="utf-8")
        remote = fetch(manifest["repository"], ticket["number"])
        if remote["number"] != ticket["number"]:
            raise ValueError("GitHub 回傳的工作票編號不符")
        errors.extend(f"#{ticket['number']}：{error}" for error in check_ticket(local, remote, phase))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="包含 repository 與 tickets 的發布索引")
    parser.add_argument("--issue", type=int)
    parser.add_argument("--phase", choices=("audit", "before-close", "after-close"), default="audit")
    args = parser.parse_args(argv)
    if args.phase != "audit" and args.issue is None:
        parser.error("結案前／後檢查需指定 --issue")
    gh = shutil.which("gh")
    if gh is None and os.name == "nt":
        installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "GitHub CLI/gh.exe"
        gh = str(installed) if installed.is_file() else None
    if gh is None:
        print("無法核對：找不到 GitHub CLI", file=sys.stderr)
        return 2

    def fetch(repo, number):
        result = subprocess.run(
            [gh, "issue", "view", str(number), "--repo", repo, "--json", "number,state,body"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if result.returncode:
            raise ValueError(result.stderr.strip() or "GitHub 讀取失敗")
        return json.loads(result.stdout)

    try:
        errors = inspect_tickets(args.manifest, args.issue, args.phase, fetch)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"無法核對：{exc}", file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors))
        return 1
    print("工作票狀態檢查通過；勾選不代表工具已驗證實際操作證據。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
