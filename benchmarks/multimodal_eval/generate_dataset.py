"""multimodal_eval_v1 数据集生成器(确定性,seed 固定)。

用法:
    python -X utf8 benchmarks/multimodal_eval/generate_dataset.py \
        [--out E:/MASE-runs/datasets/multimodal_eval_v1] [--skip-audio]

产物:
    <out>/files/<case_id>.{png,pdf,wav}   媒体二进制(仓外冻结)
    benchmarks/multimodal_eval/cases.json      ground truth(仓内提交)
    benchmarks/multimodal_eval/manifest.json   冻结指纹(仓内提交)

设计:
- 内容由固定实体池 + random.Random(20260703) 确定性装配,cases.json 即完整
  可审计 ground truth,不依赖重新生成。
- 视觉渲染 PyMuPDF;退化(低 DPI/JPEG 重压缩/旋转/灰底)在渲染参数层实现。
- 音频经 Windows SAPI 合成(Huihui/Kangkang/Yaoyao 中文、Zira 英文);
  TTS 输出与机器/语音包相关,因此**以冻结后的二进制+sha256 为准**,
  重新生成不保证逐字节一致(manifest 校验会如实报告)。
- dev/holdout 切分按 case_id 尾号:尾号 %5 == 0 → dev(约 20%),其余 holdout。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
DATASET_NAME = "multimodal_eval_v1"
SEED = 20260703
DEFAULT_OUT = Path("E:/MASE-runs/datasets") / DATASET_NAME

# ---------------------------------------------------------------------------
# 实体池(确定性装配的原料;全部虚构)
# ---------------------------------------------------------------------------
COMPANIES_ZH = ["泰岳智造", "华澜数据", "启明重工", "蓝鲸物流", "云帆生物"]
COMPANIES_EN = ["Northwind Systems", "Apex Logistics", "Bluepeak Analytics", "Ironwood Manufacturing"]
PEOPLE_ZH = ["张伟", "李娜", "王强", "赵敏", "刘洋", "陈静"]
PEOPLE_EN = ["Sarah Chen", "Michael Torres", "Emma Larsson", "David Okafor"]
CITIES_ZH = ["上海市浦东新区张江路88号", "北京市海淀区中关村大街27号", "深圳市南山区科技园南路15号"]
PROJECTS = ["Phoenix", "Kunlun", "Aurora", "Tianshan", "Meridian"]


def _amount_zh(rng: random.Random) -> tuple[str, str]:
    """返回 (展示串, 归一化锚串)。锚串选归一化后稳定的数字核。"""
    value = rng.choice([8640, 86400, 129500, 47300, 265000, 58200, 731000])
    return f"¥{value:,}", str(value)


def _po_number(rng: random.Random) -> str:
    return f"PO-2026-{rng.randint(1000, 9999)}"


def _inv_number(rng: random.Random) -> str:
    return f"INV-{rng.randint(100000, 999999)}"


def _date(rng: random.Random) -> str:
    return f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"


# ---------------------------------------------------------------------------
# 案例构造:每类模板返回 (标题行列表, 正文行列表, anchors, facts, qa)
# 行内容即渲染文本,也是 ground truth 的唯一来源 → 可审计。
# ---------------------------------------------------------------------------

def _mk_purchase_order(rng: random.Random, lang: str) -> dict[str, Any]:
    po = _po_number(rng)
    amount_disp, amount_anchor = _amount_zh(rng)
    company = rng.choice(COMPANIES_ZH if lang == "zh" else COMPANIES_EN)
    person = rng.choice(PEOPLE_ZH if lang == "zh" else PEOPLE_EN)
    date = _date(rng)
    if lang == "zh":
        lines = [
            f"采购订单  {po}",
            f"供应商: {company}",
            f"订单总额: {amount_disp}(含税)",
            f"交付日期: {date}",
            f"采购负责人: {person}",
            "付款条件: 货到 30 天内电汇",
        ]
        qa = [{"q": f"采购订单 {po} 的总额是多少?", "answer_anchors": [amount_anchor]}]
    else:
        lines = [
            f"PURCHASE ORDER  {po}",
            f"Supplier: {company}",
            f"Order total: EUR {amount_anchor} (tax incl.)",
            f"Delivery date: {date}",
            f"Buyer: {person}",
            "Payment terms: wire transfer net 30",
        ]
        qa = [{"q": f"What is the total of purchase order {po}?", "answer_anchors": [amount_anchor]}]
    return {
        "lines": lines,
        "anchors_fulltext": [po, amount_anchor, date],
        "expected_facts": [
            {"key_hint": "order_total", "value_anchors": [amount_anchor]},
            {"key_hint": "delivery_date", "value_anchors": [date]},
        ],
        "qa": qa,
    }


def _mk_meeting_minutes(rng: random.Random, lang: str) -> dict[str, Any]:
    project = rng.choice(PROJECTS)
    person = rng.choice(PEOPLE_ZH if lang == "zh" else PEOPLE_EN)
    date = _date(rng)
    amount_disp, amount_anchor = _amount_zh(rng)
    if lang == "zh":
        lines = [
            f"{project} 项目周会纪要 ({date})",
            f"决议一: {project} 项目二期预算核定为 {amount_disp}。",
            f"决议二: {person} 负责在 {date} 前提交风险评估报告。",
            "其他: 下次周会改为每周四上午十点。",
        ]
        qa = [{"q": f"{project} 项目二期预算是多少?", "answer_anchors": [amount_anchor]}]
    else:
        lines = [
            f"{project} weekly sync minutes ({date})",
            f"Decision 1: phase-2 budget for {project} approved at EUR {amount_anchor}.",
            f"Decision 2: {person} to deliver the risk assessment by {date}.",
            "Note: the sync moves to Thursdays 10am.",
        ]
        qa = [{"q": f"What phase-2 budget was approved for {project}?", "answer_anchors": [amount_anchor]}]
    return {
        "lines": lines,
        "anchors_fulltext": [project, amount_anchor],
        "expected_facts": [{"key_hint": "budget", "value_anchors": [amount_anchor]}],
        "qa": qa,
    }


def _mk_contract_clause(rng: random.Random, lang: str) -> dict[str, Any]:
    company = rng.choice(COMPANIES_ZH if lang == "zh" else COMPANIES_EN)
    date = _date(rng)
    penalty = rng.choice(["0.5%", "1.2%", "0.8%"])
    if lang == "zh":
        lines = [
            "服务合同(节选) 第七条 违约责任",
            f"甲方: {company}",
            f"7.1 任一方逾期履约的,每逾期一日按合同总价的 {penalty} 支付违约金。",
            f"7.2 本合同有效期至 {date}。",
        ]
        qa = [{"q": f"与 {company} 合同的每日违约金比例是多少?", "answer_anchors": [penalty]}]
    else:
        lines = [
            "SERVICE AGREEMENT (extract) - Article 7 Liability",
            f"Party A: {company}",
            f"7.1 Late performance incurs liquidated damages of {penalty} of the contract price per day.",
            f"7.2 This agreement remains in force until {date}.",
        ]
        qa = [{"q": f"What is the daily penalty rate in the {company} agreement?", "answer_anchors": [penalty]}]
    return {
        "lines": lines,
        "anchors_fulltext": [penalty, date],
        "expected_facts": [{"key_hint": "penalty_rate", "value_anchors": [penalty]}],
        "qa": qa,
    }


def _mk_invoice(rng: random.Random, lang: str) -> dict[str, Any]:
    inv = _inv_number(rng)
    amount_disp, amount_anchor = _amount_zh(rng)
    company = rng.choice(COMPANIES_ZH if lang == "zh" else COMPANIES_EN)
    date = _date(rng)
    if lang == "zh":
        lines = [
            f"增值税发票  {inv}",
            f"销售方: {company}",
            f"价税合计: {amount_disp}",
            f"开票日期: {date}",
        ]
        qa = [{"q": f"发票 {inv} 的价税合计是多少?", "answer_anchors": [amount_anchor]}]
    else:
        lines = [
            f"INVOICE  {inv}",
            f"Vendor: {company}",
            f"Total incl. tax: EUR {amount_anchor}",
            f"Issue date: {date}",
        ]
        qa = [{"q": f"What is the total of invoice {inv}?", "answer_anchors": [amount_anchor]}]
    return {
        "lines": lines,
        "anchors_fulltext": [inv, amount_anchor],
        "expected_facts": [{"key_hint": "invoice_total", "value_anchors": [amount_anchor]}],
        "qa": qa,
    }


def _mk_confusable_numbers(rng: random.Random, lang: str) -> dict[str, Any]:
    """L3 陷阱:同页出现 8,640 / 86,400 / 864,000 三个易混金额,问其中一个。"""
    project = rng.choice(PROJECTS)
    lines_zh = [
        f"{project} 项目成本核算表",
        "一期硬件采购: ¥8,640",
        "二期实施服务: ¥86,400",
        "三期运维总包: ¥864,000",
        "注: 以上均为含税价。",
    ]
    lines_en = [
        f"{project} cost breakdown",
        "Phase-1 hardware: EUR 8,640",
        "Phase-2 services: EUR 86,400",
        "Phase-3 operations: EUR 864,000",
        "All amounts include tax.",
    ]
    lines = lines_zh if lang == "zh" else lines_en
    q = f"{project} 二期实施服务的金额是多少?" if lang == "zh" else f"What is the {project} phase-2 services amount?"
    return {
        "lines": lines,
        "anchors_fulltext": ["8640", "86400", "864000"],
        "expected_facts": [{"key_hint": "phase2", "value_anchors": ["86400"]}],
        "qa": [{"q": q, "answer_anchors": ["86400"]}],
    }


def _mk_negative_decorative(rng: random.Random, lang: str) -> dict[str, Any]:
    """负例:纯装饰/口号页,无可提取业务事实。"""
    company = rng.choice(COMPANIES_ZH if lang == "zh" else COMPANIES_EN)
    lines = (
        [f"{company}", "创新 · 协作 · 卓越", "———", "企业文化墙"]
        if lang == "zh"
        else [f"{company}", "Innovate. Collaborate. Excel.", "———", "Culture wall"]
    )
    return {"lines": lines, "anchors_fulltext": [], "expected_facts": [], "qa": []}


_VISUAL_TEMPLATES = [_mk_purchase_order, _mk_meeting_minutes, _mk_contract_clause, _mk_invoice]


def _mk_audio_script(rng: random.Random, lang: str, difficulty: int) -> dict[str, Any]:
    project = rng.choice(PROJECTS)
    amount_disp, amount_anchor = _amount_zh(rng)
    person = rng.choice(PEOPLE_ZH if lang == "zh" else PEOPLE_EN)
    date = _date(rng)
    if lang == "zh":
        base = f"会议决定,{project} 项目的预算是 {amount_anchor} 元,由 {person} 负责执行。"
        filler = "另外说一下,今天午餐订的是楼下那家,大家记得去前台取餐。会议室下周装修,先换到三楼。"
        dense = f"补充三点:第一,验收日期定在 {date};第二,尾款比例是百分之三十;第三,对接人换成 {person}。"
        qa = [{"q": f"{project} 项目的预算是多少?", "answer_anchors": [amount_anchor]}]
    else:
        base = f"The meeting approved a budget of {amount_anchor} euros for project {project}, owned by {person}."
        filler = "Also, lunch is at the usual place downstairs, and the meeting room moves to floor three next week."
        dense = f"Three updates: acceptance is due {date}; the final payment is thirty percent; the new contact is {person}."
        qa = [{"q": f"What budget was approved for project {project}?", "answer_anchors": [amount_anchor]}]
    script = base
    anchors = [amount_anchor]
    facts = [{"key_hint": "budget", "value_anchors": [amount_anchor]}]
    if difficulty >= 2:
        script = f"{base} {filler}"
    if difficulty >= 3:
        script = f"{base} {filler} {dense}"
        anchors.append(date)
        facts.append({"key_hint": "acceptance_date", "value_anchors": [date]})
    return {"script": script, "anchors_fulltext": anchors, "expected_facts": facts, "qa": qa}


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def _render_visual(case: dict[str, Any], out_file: Path) -> None:
    import fitz

    degrade = case.get("degrade", {})
    doc = fitz.open()
    pages_lines: list[list[str]] = case["_pages_lines"]
    for lines in pages_lines:
        page = doc.new_page()
        if degrade.get("gray_bg"):
            page.draw_rect(page.rect, color=None, fill=(0.82, 0.82, 0.82))
        y = 80
        font = "china-s" if case["language"] in {"zh", "mixed"} else "helv"
        size = degrade.get("font_size", 13)
        for i, line in enumerate(lines):
            page.insert_text((60, y), line, fontsize=(size + 4 if i == 0 else size), fontname=font)
            y += int(size * (2.6 if i == 0 else 2.0))
    if out_file.suffix == ".pdf":
        doc.save(str(out_file))
        doc.close()
        return
    page = doc[0]
    dpi = degrade.get("dpi", 150)
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    if degrade.get("rotate"):
        matrix = matrix.prerotate(degrade["rotate"])
    pixmap = page.get_pixmap(matrix=matrix)
    if degrade.get("jpeg_quality"):
        out_file.with_suffix(".jpg")
        pixmap.save(str(out_file), jpg_quality=degrade["jpeg_quality"])
    else:
        pixmap.save(str(out_file))
    doc.close()


def _render_audio(script: str, voice: str, out_file: Path) -> None:
    escaped = script.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SelectVoice('{voice}'); "
        f"$s.SetOutputToWaveFile('{out_file}'); "
        f"$s.Speak('{escaped}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=180)
    if not out_file.exists() or out_file.stat().st_size < 1000:
        raise RuntimeError(f"TTS 合成失败: {out_file}")


# ---------------------------------------------------------------------------
# 数据集装配
# ---------------------------------------------------------------------------

def build_cases(rng: random.Random) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    counter = 0

    def add_visual(difficulty: int, lang: str, template, *, degrade: dict | None = None,
                   multipage: bool = False, ext: str = ".png") -> None:
        nonlocal counter
        counter += 1
        body = template(rng, "zh" if lang == "mixed" else lang)
        case_id = f"vis-L{difficulty}-{counter:03d}"
        pages = [body["lines"]]
        if multipage:
            extra = template(rng, "en")
            pages.append(extra["lines"])
            body["anchors_fulltext"] += extra["anchors_fulltext"]
            body["expected_facts"] += extra["expected_facts"]
            body["qa"] += extra["qa"]
        cases.append({
            "case_id": case_id,
            "modality": "pdf" if ext == ".pdf" else "image",
            "difficulty": difficulty,
            "language": lang,
            "file": f"files/{case_id}{ext}",
            "negative": template is _mk_negative_decorative,
            "degrade": degrade or {},
            "_pages_lines": pages,
            "anchors_fulltext": body["anchors_fulltext"],
            "expected_facts": body["expected_facts"],
            "qa": body["qa"],
        })

    # L1 干净 ×15(4 模板 × zh/en 轮转)
    for i in range(15):
        add_visual(1, ("zh", "en")[i % 2], _VISUAL_TEMPLATES[i % 4])
    # L2 退化 ×15
    degrades = [
        {"dpi": 75}, {"jpeg_quality": 30}, {"rotate": 3}, {"rotate": -3},
        {"gray_bg": True}, {"dpi": 75, "gray_bg": True}, {"font_size": 9},
        {"jpeg_quality": 25, "dpi": 100},
    ]
    for i in range(15):
        add_visual(2, ("zh", "en")[i % 2], _VISUAL_TEMPLATES[(i + 1) % 4],
                   degrade=degrades[i % len(degrades)],
                   ext=".jpg" if degrades[i % len(degrades)].get("jpeg_quality") else ".png")
    # L3 困难 ×12:多页 PDF ×6 + 易混数字 ×6
    for i in range(6):
        add_visual(3, "mixed", _VISUAL_TEMPLATES[i % 4], multipage=True, ext=".pdf")
    for i in range(6):
        add_visual(3, ("zh", "en")[i % 2], _mk_confusable_numbers)
    # 负例 ×6
    for i in range(6):
        add_visual(1, ("zh", "en")[i % 2], _mk_negative_decorative)

    # 音频 ×18
    voices_zh = ["Microsoft Huihui Desktop", "Microsoft Kangkang", "Microsoft Yaoyao"]
    voice_en = "Microsoft Zira Desktop"
    audio_plan = [(1, 8), (2, 6), (3, 4)]
    for difficulty, count in audio_plan:
        for i in range(count):
            counter += 1
            lang = ("zh", "en")[i % 2]
            body = _mk_audio_script(rng, lang, difficulty)
            case_id = f"aud-L{difficulty}-{counter:03d}"
            voice = voice_en if lang == "en" else voices_zh[(i // 2) % len(voices_zh)]
            cases.append({
                "case_id": case_id,
                "modality": "audio",
                "difficulty": difficulty,
                "language": lang,
                "file": f"files/{case_id}.wav",
                "negative": False,
                "voice": voice,
                "_script": body["script"],
                "anchors_fulltext": body["anchors_fulltext"],
                "expected_facts": body["expected_facts"],
                "qa": body["qa"],
            })

    # 干扰问答 ×6(挂在既有案例上,答案不在该案例语料 → 期望不可召回)
    distractors_zh = ["公司年会的抽奖一等奖是什么?", "新办公楼的物业电话是多少?", "食堂周三的菜单是什么?"]
    distractors_en = ["What is the CEO's home address?", "Which airline was booked for the offsite?",
                      "What is the wifi password of the branch office?"]
    eligible = [c for c in cases if not c["negative"] and c["modality"] != "audio"][:6]
    for i, case in enumerate(eligible):
        text = distractors_zh[i % 3] if case["language"] != "en" else distractors_en[i % 3]
        case["distractor_qa"] = [{"q": text, "must_not_recall": True}]

    return cases


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--skip-audio", action="store_true", help="只生成视觉部分(调试用)")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    files_dir = out_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    cases = build_cases(rng)

    for case in cases:
        target = out_dir / case["file"]
        if case["modality"] == "audio":
            if args.skip_audio:
                continue
            _render_audio(case["_script"], case["voice"], target)
        else:
            _render_visual(case, target)
        case["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        case["byte_size"] = target.stat().st_size

    # 内部渲染字段不进 ground truth 文件(_script 保留:音频的可审计文字底稿)
    for case in cases:
        case.pop("_pages_lines", None)
        if "_script" in case:
            case["tts_script"] = case.pop("_script")

    # dev/holdout:case 序号 %5 == 0 → dev
    for index, case in enumerate(cases):
        case["split"] = "dev" if index % 5 == 0 else "holdout"

    for case in cases:
        case["lane"] = "synthetic"

    cases_path = _REPO / "benchmarks" / "multimodal_eval" / "cases_synthetic.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[synthetic] {len(cases)} cases -> {out_dir}")
    print(f"[ground-truth] {cases_path}")
    print("下一步: python -X utf8 benchmarks/multimodal_eval/build_suite.py 合并外部 lane 并冻结 manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
