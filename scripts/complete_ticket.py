"""同步已驗收的本機工作票並結案；以 python -m scripts.complete_ticket 執行。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from scripts.check_ticket_completion import acceptance_items, check_ticket, find_gh


def normalized(body):
    return body.replace("\r", "")


def complete_ticket(local_body, api):
    """驗收需先完成；此命令不產生證據、不勾選、不改驗收範圍。"""
    local_body = normalized(local_body)
    errors = check_ticket(local_body, {"body": local_body, "state": "OPEN"}, "before-close")
    if errors:
        raise ValueError("\n".join(errors))
    remote = api.read()
    if [text for _, text in acceptance_items(remote["body"])] != [
        text for _, text in acceptance_items(local_body)
    ]:
        raise ValueError("本機與 GitHub 驗收條件不同；請先核對需求變更，不能用結案命令覆寫")
    if normalized(remote["body"]) != local_body:
        api.update(local_body)
    synced = api.read()
    if normalized(synced["body"]) != local_body:
        raise ValueError("GitHub 內文同步讀回不符，尚未關閉 issue")
    if synced["state"] != "CLOSED":
        api.close()
    completed = api.read()
    errors = check_ticket(local_body, completed, "after-close")
    if normalized(completed["body"]) != local_body:
        errors.append("結案後 GitHub 內文與本機不一致")
    if errors:
        raise ValueError("\n".join(errors))
    return completed


class GitHubTicket:
    def __init__(self, gh, repo, number):
        self.gh, self.repo, self.number = gh, repo, number

    def command(self, *args):
        result = subprocess.run(
            [self.gh, "issue", *args, "--repo", self.repo],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if result.returncode:
            raise ValueError(result.stderr.strip() or "GitHub 操作失敗")
        return result.stdout

    def read(self):
        data = json.loads(self.command("view", str(self.number), "--json", "number,state,body,url"))
        if data["number"] != self.number:
            raise ValueError("GitHub 回傳的工作票編號不符")
        return data

    def update(self, body):
        with tempfile.TemporaryDirectory(prefix="chess-ticket-") as temporary:
            path = Path(temporary) / "body.md"
            path.write_text(body, encoding="utf-8", newline="\n")
            self.command("edit", str(self.number), "--body-file", str(path))

    def close(self):
        self.command("close", str(self.number), "--reason", "completed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--issue", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        gh = find_gh()
        if gh is None:
            raise ValueError("找不到 GitHub CLI")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        entries = [ticket for ticket in manifest["tickets"] if ticket["number"] == args.issue]
        if len(entries) != 1:
            raise ValueError("發布索引沒有唯一對應的工作票；不處理父規格")
        path = (args.manifest.parent / entries[0]["file"]).resolve()
        if not path.is_relative_to(args.manifest.parent.resolve()):
            raise ValueError("工作票路徑超出發布索引目錄")
        local = path.read_text(encoding="utf-8")
        api = GitHubTicket(gh, manifest["repository"], args.issue)
        complete_ticket(local, api)
        print(f"#{args.issue} CLOSED：GitHub 內文與本機驗收一致。請同步批次索引與開發計畫並提交收尾。")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"結案同步未完成：{exc}。修正後可重跑；不要回報整票完成。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
