#!/usr/bin/env python3
"""ポッドキャストの字幕を、読める連続した文章に整形する。

やることは4つ:
  1. 番号の行、時間軸、VTT/HTML のタグ、重複した行を消す
  2. 細切れになった字幕の行をつなぎ、文に戻す
  3. 時間の間隔と句読点で段落を分ける
  4. ついでに統計（漢字数、段落数、長さの見積もり）を出す

使い方:
    python3 prep_transcript.py 入力.srt
    python3 prep_transcript.py 入力.srt -o 整形稿.md
    python3 prep_transcript.py 入力.txt --speakers      # 話し手のラベルだけを一覧にする

SRT / VTT（時間軸付き）と txt / md に対応する。空行のあるプレーンテキストは、元の空行での段落分けを保つ。
"""
import argparse
import re
import sys
from pathlib import Path

TS = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}\s*-->")
NUM = re.compile(r"^\s*\d+\s*$")
TAG = re.compile(r"<[^>]{1,40}>")
SPEAKER = re.compile(
    r"^\s*\*{0,2}\s*(?:\[|【)?\s*([\u4e00-\u9fffA-Za-z0-9 _\-]{1,8}?)\s*(?:\]|】)?\s*[:：]\s*\*{0,2}\s*")
NO_LABEL = ("说", "道", "问", "答", "是", "有", "我见", "注意")   # これらは人名らしくないので、話し手として扱わない
HEADING = ("#", ">", "---", "|")   # そのまま残すブロックで、結合しない
PARA_GAP = 1.5     # 秒。これより間隔が空いたら段落を替える
PARA_CHARS = 140   # 段落の長さのゆるい上限。文末に来て、かつこれを超えたら段落を分ける
HARD_CHARS = 300   # 厳密な上限。句読点のない ASR の書き起こしもこれで分ける


def parse_time(s):
    s = (s or "").strip().replace(",", ".")
    if not s:
        return None
    parts = [x for x in re.split(r"[:.]", s) if x != ""]
    try:
        n = [float(x) for x in parts]
    except ValueError:
        return None
    if len(n) >= 4:
        h, m, sec, ms = n[:4]
        return h * 3600 + m * 60 + sec + ms / 1000
    if len(n) == 3:
        h, m, sec = n
        return h * 3600 + m * 60 + sec
    if len(n) == 2:
        m, sec = n
        return m * 60 + sec
    return n[0] if n else None


def parse(text):
    """[(start, end, text), ...] を返す"""
    cues = []
    if "-->" in text:
        for block in re.split(r"\n\s*\n", text):
            lines = [l for l in block.split("\n") if l.strip()]
            if not lines:
                continue
            i = 0
            if NUM.match(lines[0]):
                i = 1
            if i < len(lines) and "-->" in lines[i]:
                a, _, b = lines[i].partition("-->")
                start, end = parse_time(a), parse_time(b.split()[0] if b.split() else "")
                body = " ".join(lines[i + 1:])
                if body.strip():
                    cues.append((start, end, TAG.sub("", body).strip()))
                continue
            cues.append((None, None, TAG.sub("", " ".join(lines)).strip()))
        return cues

    # プレーンテキスト: 1行を1件とし、句読点と話し手による結合は build() に任せる
    for line in text.split("\n"):
        line = TAG.sub("", line).strip()
        if line and not TS.match(line) and not NUM.match(line):
            cues.append((None, None, line))
    return cues


def speaker_of(txt):
    m = SPEAKER.match(txt)
    if not m:
        return None
    label = m.group(1).strip()
    if label.endswith(NO_LABEL) or len(label) > 8:
        return None
    return label


def join_fragments(a, b):
    if not a:
        return b
    if re.search(r"[A-Za-z0-9]$", a) and re.match(r"^[A-Za-z0-9]", b):
        return a + " " + b
    return a + b


def is_standalone(txt):
    return txt.lstrip().startswith(HEADING)


def build(cues, split_speaker=True):
    """cue をつないで段落にする。

    ルール: 同じ話し手の続いた断片は結合する（ASR はよく1文を何件にも分ける）。話し手が替わったとき、
    時間が PARA_GAP 秒より空いたとき、同じ人の話が PARA_CHARS 字までたまって文末に来たときは、
    段落を分ける。見出しと引用の行は前後で分け、それだけで1段落にする。
    """
    paras, buf, buf_start, last_end, cur = [], "", None, None, None
    for start, end, txt in cues:
        txt = txt.strip()
        if not txt:
            continue
        if is_standalone(txt):
            if buf:
                paras.append((buf_start, buf))
            buf, buf_start, cur = "", None, None
            paras.append((start, txt))
            last_end = end
            continue
        at_end = bool(re.search(r"[。！？!?]\s*$", buf))
        me = speaker_of(txt)
        brk = False
        if buf:
            if split_speaker and me and cur and me != cur:
                brk = True
            if last_end is not None and start is not None and start - last_end > PARA_GAP:
                brk = True
            if at_end and len(buf) >= PARA_CHARS:
                brk = True
            if len(buf) >= HARD_CHARS:
                brk = True
        if brk:
            paras.append((buf_start, buf))
            buf, buf_start = "", None
        if me:
            cur = me
        if buf_start is None:
            buf_start = start
        buf = join_fragments(buf, txt)
        if end is not None:
            last_end = end
    if buf:
        paras.append((buf_start, buf))
    return [p for p in paras if p[1].strip()]


def split_long(para, limit=260):
    """長すぎる段落を文末で分ける。"""
    if len(para) <= limit:
        return [para]
    out, buf = [], ""
    for sent in re.findall(r"[^。！？!?]*[。！？!?]|[^。！？!?]+$", para):
        if not sent:
            continue
        buf += sent
        if len(buf) >= limit:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def fmt_time(sec):
    if sec is None:
        return "—"
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("-o", "--out")
    ap.add_argument("--no-split-speaker", action="store_true",
                    help="話し手が替わっても段落を分けない")
    ap.add_argument("--speakers", action="store_true", help="話し手のラベルだけを一覧にする")
    args = ap.parse_args()

    raw = Path(args.path).read_text(encoding="utf-8", errors="replace")
    cues = parse(raw)
    if not cues:
        sys.exit(f"内容を読み取れなかった: {args.path}")

    if args.speakers:
        found = {}
        for _, _, t in cues:
            m = SPEAKER.match(t)
            if m:
                found[m.group(1)] = found.get(m.group(1), 0) + 1
        print(f"{len(cues)} 件を読み取った")
        for k, v in sorted(found.items(), key=lambda x: -x[1]):
            print(f"  {k}  {v}")
        return

    paras = []
    for start, body in build(cues, not args.no_split_speaker):
        for chunk in split_long(body):
            paras.append((start, chunk))

    zh = len(re.findall(r"[\u4e00-\u9fff]", "".join(p for _, p in paras)))
    last = cues[-1][1] or cues[-1][0]
    dur = fmt_time(last)

    # 隣り合った同じ段落を1つにする（ASR でよく起きる）
    dedup = []
    for s, p in paras:
        if dedup and dedup[-1][1].strip() == p.strip():
            continue
        dedup.append((s, p))
    dropped = len(paras) - len(dedup)
    paras = dedup

    lines = []
    for s, p in paras:
        p = re.sub(r"\s*\n\s*", " ", p).strip()
        lines.append(f"[{fmt_time(s)}] {p}" if s is not None and not is_standalone(p) else p)
    body = "\n\n".join(lines)

    heads = sum(1 for _, p in paras if p.lstrip().startswith("#"))
    punct = len(re.findall(r"[。！？!?]", "".join(p for _, p in paras)))
    stats = (f"# 統計: 漢字 {zh}、段落 {len(paras)}、元の断片 {len(cues)}、章の見出し {heads}、"
             f"長さ 約 {dur}、重複を除いた段落 {dropped}")
    if punct < 0.5 * len(paras):
        stats += ("\n# 注意: 文末の句読点が少ない（ASR による）ので、段落の区切りは長さで決めている。"
                  "次に要点を整理する前に、句読点を補い、1文ずつ区切る。")
    if args.out:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(stats, file=sys.stderr)
        print(f"{args.out} に書き出した", file=sys.stderr)
    else:
        print(body)
        print("\n" + stats, file=sys.stderr)


if __name__ == "__main__":
    main()
