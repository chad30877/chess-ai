import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.learning.heldout import freeze_heldout, evaluate_heldout, load_heldout


def main():
    parser = argparse.ArgumentParser(description='凍結候選的最終教師誤差評估；不以結果選擇或調整候選')
    sub = parser.add_subparsers(dest='action', required=True)
    freeze = sub.add_parser('freeze', help='先凍結完整比較候選及評估用途')
    freeze.add_argument('final_path'); freeze.add_argument('--root', default='.')
    evaluate = sub.add_parser('evaluate', help='評估已完成標記的資料集測試組')
    evaluate.add_argument('heldout_path'); evaluate.add_argument('label_path')
    show = sub.add_parser('show', help='查看保存的評估與限制')
    show.add_argument('heldout_path')
    args = parser.parse_args()
    if args.action == 'freeze':
        print(freeze_heldout(args.root, args.final_path))
    elif args.action == 'evaluate':
        print(json.dumps(evaluate_heldout(args.heldout_path, args.label_path), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(load_heldout(args.heldout_path), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
