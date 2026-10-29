#!/usr/bin/env python3
"""完成稿のAIっぽさの自己チェック。

ルールと人の側の基準値は https://github.com/larashero3-dotcom/lieflat-less-ai-tone （MIT）から取った。
そこでは5つのモデルが生成した300本と人が書いた329本（629本、95,551文、45,721段落）で
「AIの文体」の候補の特徴を1つずつ検証し、本当に区別に役立つものだけを残している。ここの正規表現は
その scripts/ から、人の側の基準値はその RESEARCH.md から写した（人の側のコーパスは公開されておらず、手元で計算し直せない）。
日本語のルールは中国語のルールを日本語に置き換えたもので、人の側の基準値は日本語ではまだ測られていない。

使い方:
    python3 check_style.py 完成稿.md
    python3 check_style.py 完成稿.md --quiet      # 結論だけを出し、実例は出さない
    python3 check_style.py 完成稿.md --lang ja    # 言語を指定する（既定はかなの多さで自動判定）

判断は自分の目でも確かめる。正規表現は字面しか見ないので、かぎかっこの中の元の言葉、対話形式、読点（、）の多い列挙は誤検出になる。
"""
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 名前 -> (正規表現, 人の基準値/1,000字 または None, 必ず禁止する項目か)
ZH_RULES = [
    ("ダッシュ", r"—", 0.80, True),
    ("対比構文（XではなくY）", r"(?:不是|并非|不在于)[^，。！？\n]{1,20}[，]?(?:而是|而在于)", 0.22, True),
    ("まとめ口調", r"(?:本质上|核心是|核心在于|归根结底|综上所述|换句话说|换言之|值得注意的是|值得一提的是|说到底)", None, True),
    ("序数詞の小見出し", r"(?:^|\n)\s*(?:首先|其次|再次|最后|第一|第二|第三|一方面|另一方面)[，、]", 0.06, False),
    ("予告のコロン", (r"(?:一句话(?:总结|说|概括)|简单说|说白了|总结|小结|结论|核心(?:是|在于|观点)?"
                r"|关键(?:是|在于)?|重点(?:是)?|原因(?:如下|有|在于)?|问题(?:是|在于)?"
                r"|答案(?:是)?|本质(?:是|上)?|定义(?:是)?|具体(?:来说|如下|包括)?"
                r"|举例(?:来说)?|换句话说|也就是说|我的(?:观点|判断|结论)|建议(?:是)?)[：:]"), 0.08, False),
    ("中身のない文で箇条書きを導く", r"(?:^|\n)([^\n。！？]{0,40})[：:][ \t]*\n\s*[-*\d]", 0.03, False),
    ("擬人化した比喩", r"(?:像|相当于|如同|好比)(?:一个|一位|一名|一种)?[^，。\n]{0,6}(?:导师|秘书|助手|顾问|管家|审查员|实习生|教练|伙伴|搭档|同事|专家)", 0.002, False),
    ("話し手の態度を代わりに描く", r"(?:说|讲|回答|介绍|解释|强调)得(?:很|挺|特别|非常)(?:重|轻|坦白|坦诚|真诚|直接|认真|激动|平静|无奈|克制|小声|大声|慢|快)|(?:他|她|他们|对方|嘉宾|主持人)的(?:语气|神情|表情|态度)", None, True),
    ("動詞の名詞化", r"(?:完成|实现|进行|开展)了?(?:对)?[^，。\n]{0,10}的(?:优化|提升|调整|分析|改造|升级)", 0.005, False),
    ("文頭の接続詞", r"(?:^|\n)\s*(?:然而|因此|此外|与此同时|换言之|总而言之)[，、]", 0.03, False),
    ("これは〜を意味する", r"(?:这意味着|这表明|这说明|换句话说)", 0.15, False),
    ("〜するときに", r"当[^，。\n]{2,20}(?<!的时候)时，", 0.26, False),
    ("前置きの話題の枠", r"(?:对于[^，。\n]{2,15}来说|对[^，。\n]{2,15}而言|就[^，。\n]{2,15}而言|在[^，。\n]{2,12}方面)", 0.22, False),
    ("長すぎる前置きの連体修飾", r"(?:一个|一种|一套|这种|这个)[^，。、；：！？\n]{15,}的[\u4e00-\u9fff]{2,5}", 0.42, False),
    ("読点（、）の列挙が多すぎる", r"[^，。！？；：、\n]{1,14}、[^，。！？；、\n]{1,14}、[^，。！？；：、\n]{1,14}", 1.78, False),
]

# 日本語には人の基準値の実測がないので、基準値はすべて None にしている。中国語のルールを日本語に置き換えたもので、
# 「〜するときに」「長すぎる前置きの連体修飾」「読点の列挙」は日本語ではふつうの書き方なので入れていない。
JA_RULES = [
    ("ダッシュ", r"—{1,2}|―{1,2}|─{2}", None, True),
    ("対比構文（XではなくY）", r"(?:ではなく|じゃなくて?)", None, True),
    ("まとめ口調", r"(?:本質的には|本質は|核心は|つまるところ|要するに|言い換えれば|換言すれば|注目すべき(?:は|点は)|特筆すべきは|以上をまとめると|まとめると|結局のところ)", None, True),
    ("序数詞の小見出し", r"(?:^|\n)\s*(?:まず|次に|最後に|第一に|第二に|第三に|一つ目は|二つ目は|1つ目は|2つ目は|一方で|他方で)[、，]", None, False),
    ("予告のコロン", r"(?:ひとことで(?:まとめると|言うと)|簡単に言うと|要するに|結論|まとめ|ポイント|理由|問題|答え|具体的には|例えば|つまり|私の(?:考え|意見|結論))[：:]", None, False),
    ("中身のない文で箇条書きを導く", r"(?:^|\n)([^\n。！？]{0,40})[：:][ \t]*\n\s*[-*\d]", None, False),
    ("擬人化した比喩", r"[^、。\n]{0,8}(?:先生|秘書|助手|アシスタント|コンサルタント|執事|審査員|インターン|コーチ|相棒|パートナー|同僚|専門家)(?:のよう|みたい)", None, False),
    ("話し手の態度を代わりに描く", r"(?:重々しく|率直に|淡々と|熱っぽく|真剣に|興奮気味に|穏やかに|力強く|声を落として|苦笑(?:しながら|まじりに))(?:言|語|話|答|説明|強調|紹介)|(?:彼|彼女|彼ら|ゲスト|ホスト)の(?:口調|表情|態度|語気)", None, True),
    ("動詞の名詞化", r"[^、。\n]{0,10}の(?:最適化|改善|調整|分析|改修|向上|検討)を(?:行っ|行う|行い|実施|実現)", None, False),
    ("文頭の接続詞", r"(?:^|\n)\s*(?:しかし|したがって|そのため|さらに|また|このほか|それと同時に|言い換えれば|総じて)[、，]", None, False),
    ("これは〜を意味する", r"(?:これは[^。\n]{0,20}(?:を意味する|を示している)|このことから)", None, False),
    ("前置きの話題の枠", r"(?:にとっては|においては|に関しては|という点では|の面では)", None, False),
]


@dataclass(frozen=True)
class Lang:
    name: str
    unit: str
    letters: str
    rules: list
    comment: re.Pattern
    anaphor: re.Pattern
    metaphor: re.Pattern
    # 段落冒頭の自己完結した断定文: 主語と述語のそろった断定で、前の文を受けない。実録スタイルでこれが段落の冒頭に多いと、全体がスローガン集のように読める。
    assert_start: re.Pattern
    subject: re.Pattern
    attribution: re.Pattern
    quote: re.Pattern
    comma: str
    struct_human: dict
    material_human: str
    proper_nouns: str


ZH = Lang(
    name="中国語",
    unit="漢字",
    letters=r"[\u4e00-\u9fff]",
    rules=ZH_RULES,
    comment=re.compile(
        r"^(?:听起来|看起来|看上去|听上去|说白了|说到底|换句话说|意味着|值得注意|"
        r"不难看出|细看|再看|回过头看|问题在于|原因在于|结果是|有意思的是|"
        r"更重要的是|关键在于|真正的)"),
    anaphor=re.compile(r"^(?:这|那|其|此|上面|前面|刚才|以上|该|它|他|她|它们|他们|同样|类似|相比|反过来|但|不过|所以|因此|于是|而|另|除此|与此)"),
    metaphor=re.compile(r"^(?:像|就像|好比|好像|仿佛|如同|这就像)"),
    # キーワードは「〜である」「〜ではない」に当たる判断の語だけにする。「〜できる」「〜がある」に当たる語まで含めると広すぎて、「能力の限界の話になると」のような文まで断定と誤検出する。
    assert_start=re.compile(r"^[^，。！？；\n“”\"：]{2,14}(?:是|不是|就是|在于|等于|属于)"),
    subject=re.compile(r"^(?:他|她|它|他们|我们|你|我|Noah|主持人)"),
    attribution=re.compile(r"^[A-Za-z\u4e00-\u9fff]{2,6}(?:说|问|答|介绍|形容)"),
    # 直接引用（中国語と英語の引用符の両方を数え、引用符の中は2字以上）
    quote=re.compile(r"[“\"]([^”\"]{2,})[”\"]"),
    comma="，",
    struct_human={
        "前を受けない評言の段落/最初以外%": 0.14,
        "同じ構造の2文の連続/100段落": 4.81,
        "比喩で始まる段落/100段落": 0.38,
    },
    material_human="人の基準値は 17.92",
    proper_nouns="中国語",
)

JA = Lang(
    name="日本語",
    unit="文字",
    letters=r"[\u3040-\u30ff\u4e00-\u9fff]",
    rules=JA_RULES,
    comment=re.compile(
        r"^(?:注目すべき|興味深いのは|面白いのは|さらに面白いのは|問題は|重要なのは|大事なのは|"
        r"振り返って?みると|振り返ると|言い換えれば|要するに|結局|見逃せないのは|意外なのは|本当の)"),
    anaphor=re.compile(r"^(?:この|その|あの|これ|それ|あれ|こう|そう|ここ|そこ|上の|前の|先の|以上|同じ|同様|彼|彼女|彼ら|だから|しかし|でも|ただ|そして|それで|一方|逆に|反対に|ほかに|他方)"),
    metaphor=re.compile(r"^(?:まるで|たとえるなら|いわば)"),
    assert_start=re.compile(r"^[^、。！？\n「」『』：]{1,12}は[^、。！？\n]{1,24}(?:だ|である|です)$"),
    subject=re.compile(r"^(?:彼|彼女|彼ら|私|僕|我々|私たち|あなた|ホスト|ゲスト|Noah)"),
    attribution=re.compile(r"^[A-Za-z\u3040-\u30ff\u4e00-\u9fff]{1,8}(?:は|が)(?:言う|言った|話す|話した|語る|語った|答える|答えた)|と(?:彼|彼女)?は?(?:言う|話す|語る)$"),
    quote=re.compile(r"[「『\"]([^」』\"]{2,})[」』\"]"),
    comma="、",
    struct_human={},
    material_human="人の基準値は未測定",
    proper_nouns="日本語",
)

LANGS = {"zh": ZH, "ja": JA}

OK, WARN, BAD = "✅", "⚠️", "❌"
ZERO_LABEL = "前を受けない評言の段落/最初以外%"


def detect(text):
    kana = len(re.findall(r"[\u3040-\u30ff]", text))
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    return JA if kana > han * 0.1 else ZH


def count(t, lang):
    return len(re.findall(lang.letters, t))


def paragraphs(text):
    out = []
    for p in text.split("\n"):
        p = p.strip()
        if len(p) < 8 or p.startswith(("#", "|", "```", ">", "- ", "* ", "!")):
            continue
        out.append(p)
    return out


def signature(s, comma="，"):
    return (s.count(comma), "：" in s, ("（" in s or "(" in s), len(s) // 15)


def iso_pairs(para, comma="，"):
    sents = [s.strip() for s in re.split(r"[。！？]", para) if len(s.strip()) > 10]
    out = []
    for i in range(len(sents) - 1):
        if signature(sents[i], comma) == signature(sents[i + 1], comma) and signature(sents[i], comma)[0] >= 1:
            out.append((sents[i], sents[i + 1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--lang", choices=["auto", *LANGS], default="auto")
    args = ap.parse_args()

    text = Path(args.path).read_text(encoding="utf-8")
    lang = detect(text) if args.lang == "auto" else LANGS[args.lang]
    u = lang.unit
    n = count(text, lang)
    if n < 200:
        sys.exit(f"{u}が少なすぎて測れない")
    k = n / 1000

    print(f"# {Path(args.path).name}")
    print(f"言語: {lang.name}" + ("" if lang.struct_human else "（人の基準値は未測定のため、件数だけを出す）"))
    print(f"{u} {n}、段落 {len(paragraphs(text))}\n")

    print(f"## 文のレベル（1,000{u}あたり）")
    print(f"{'ルール':<22}{'該当':>6}{'1,000字あたり':>9}{'人の基準値':>10}{'倍率':>8}   判定")
    print("-" * 66)
    fails, warns = [], []
    for name, pat, human, hard in lang.rules:
        hits = re.findall(pat, text)
        c = len(hits)
        per = c / k
        ratio = f"{per / human:.1f}x" if human else "—"
        base = f"{human}" if human else "—"
        if hard and c:
            verdict = BAD
            fails.append(name)
        elif human and per > human * 3:
            verdict = WARN
            warns.append(name)
        else:
            verdict = OK
        print(f"{name:<22}{c:>6}{per:>9.2f}{base:>10}{ratio:>8}   {verdict}")
        if c and not args.quiet and verdict != OK:
            for h in hits[:8]:
                s = h if isinstance(h, str) else h[0]
                print(f"      · {re.sub(chr(10), ' ', str(s))[:70]}")
    if not fails and not warns:
        print(f"\n{OK} 文のレベルはすべて問題なし")

    print("\n## 段落のレベル")
    ps = paragraphs(text)
    nonfirst = max(len(ps) - 1, 1)
    zero = [(i, p) for i, p in enumerate(ps) if i and lang.comment.match(p) and not lang.anaphor.match(p)]
    iso2 = [(i, a, b) for i, p in enumerate(ps) for a, b in iso_pairs(p, lang.comma)]
    meta = [p for p in ps if lang.metaphor.match(p)]
    for label, val, found in [
        (ZERO_LABEL, len(zero) / nonfirst * 100, zero),
        ("同じ構造の2文の連続/100段落", len(iso2) / len(ps) * 100, iso2),
        ("比喩で始まる段落/100段落", len(meta) / len(ps) * 100, meta),
    ]:
        base = lang.struct_human.get(label)
        if base is None:
            # 基準値がなくても、前を受けない評言は段落の始め方として最も差が出た項目なので、1件でもあれば見せる。
            v = WARN if label == ZERO_LABEL and found else "—"
            print(f"{label:<22}この原稿 {val:>6.2f}   人 未測定   {v}")
        else:
            ratio = val / base if base else 0
            v = OK if ratio <= 3 else (WARN if ratio <= 6 else BAD)
            print(f"{label:<22}この原稿 {val:>6.2f}   人 {base:>5.2f}   {ratio:>5.1f}x   {v}")
        if found and not args.quiet and v not in (OK, "—"):
            for item in found[:6]:
                shown = item[-1] if isinstance(item, tuple) else item
                print(f"      · {shown[:70]}")
    # 引用は記者が書く実録の中身。低すぎれば元の言葉が要約に書き直されていて、高すぎればどの文もかぎかっこに入っている。
    quotes = lang.quote.findall(text)
    qp = sum(count(q, lang) for q in quotes) / n * 100
    qv = OK if 10 <= qp <= 28 else WARN
    print(f"\n{f'直接引用の{u}の割合%':<22}この原稿 {qp:>6.2f}   目安 10-28   {'':>5}   {qv}（{len(quotes)} か所）")

    # 段落冒頭の自己完結した断定文
    asserts = []
    for p in ps:
        first = re.split(r"[。！？]", p)[0].strip()
        if not first or first[0] in "“\"「『":
            continue
        if lang.anaphor.match(first) or lang.subject.match(first):
            continue
        if lang.attribution.search(first):
            continue
        if lang.assert_start.match(first):
            asserts.append(first)
    ra = len(asserts) / len(ps) * 100
    av = OK if ra <= 30 else (WARN if ra <= 50 else BAD)
    print(f"{'段落冒頭の断定文/段落%':<22}この原稿 {ra:>6.2f}   目安 <=30   {'':>5}   {av}")
    if asserts and not args.quiet and av != OK:
        for s in asserts[:6]:
            print(f"      · {s[:70]}")

    print(f"{f'段落の平均の長さ（{u}）':<22}{n / len(ps):>6.1f}")

    print("\n## 構造のレベル")
    bold = len(re.findall(r"\*\*[^*\n]+\*\*", text))
    bullets = len(re.findall(r"(?:^|\n)\s*(?:[-*+]|\d+\.)\s+\S", text))
    digits = len(re.findall(r"[0-9]", text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z0-9.\-]{1,}", text))
    print(f"太字 {bold}  {OK if bold == 0 else WARN}   箇条書きの行 {bullets}  {OK if bullets == 0 else WARN}")
    print(f"アラビア数字の文字 {digits}（1,000{u}あたり {digits / k:.1f}）   英字の語 {latin}（1,000{u}あたり {latin / k:.1f}）")
    print(f"材料の密度（数字、固有名詞、時期、数量。1,000{u}あたり）: {lang.material_human}。このスクリプトが数えられるのは")
    print(f"アラビア数字と英字の語の2種類だけで、漢数字と{lang.proper_nouns}の固有名詞は数えられない。この項目は人の目で確かめる。")
    print("具体的な材料が少ない原稿がいちばん直しにくい。")

    print("\n## 結論")
    if fails:
        print(f"{BAD} 必ず禁止する項目に該当: {'、'.join(fails)}。字面で禁止している表現なので、1つずつ直す。")
    if warns:
        print(f"{WARN} 1つずつ目で確かめる（誤検出の可能性あり）: {'、'.join(warns)}")
    if not fails and not warns:
        print(f"{OK} 文のレベルで直す項目はない。人の目で通読するのを忘れずに。目的語の省略、類義語への言い換え、材料の脱落はスクリプトでは見つけられない。")
    print("さらに人の目で4点を確かめる。各節の見出しから中身を予想できるか。引用を3つ選んで文字起こしと照らし合わせたか。")
    print("話し手が自分の言葉だと分からない文がないか。まるごと別の問いに答えている段落がないか。")


if __name__ == "__main__":
    main()
