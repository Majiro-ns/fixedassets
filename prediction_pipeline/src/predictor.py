"""
競技予想生成モジュール（CRE統合版）
Claude API (Haiku / Sonnet) + CREプロファイルを使って競輪・競艇の予想テキストを生成する。

【後方互換性】
  既存の generate_prediction(race_data, predictor_profile, config) 呼び出しは
  そのまま動作する（filter_type="A", sport="keirin" がデフォルト）。

【CRE統合】
  - load_cre_profile()   : mr_t_cognitive_profile.yaml を読み込む
  - build_cre_system_prompt() : filter_type に応じた CRE 注入プロンプトを構築
  - load_prompt_template()    : config/{sport}/{sport}_prompt.txt を読み込む

【dry-run モード】
  config["dry_run"] == True の場合は API 呼び出しなしで識別文字列を返す。
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import anthropic
import yaml


# ─── CRE プロファイル ────────────────────────────────────────────────────

def load_cre_profile(profile_path: str) -> dict[str, Any]:
    """CRE 認知プロファイル YAML を読み込んで返す。

    Args:
        profile_path: mr_t_cognitive_profile.yaml へのパス（ハードコード禁止）。

    Returns:
        YAML をパースした辞書。以下のキーを含む:
        - high_recovery_patterns   : 高収益キーワードリスト
        - reverse_indicator_patterns: 逆指標キーワードリスト
        - cre_generation_rules     : 生成ルール辞書

    Raises:
        FileNotFoundError: ファイルが存在しない場合
        yaml.YAMLError: YAML パースエラー時
    """
    path = Path(profile_path)
    if not path.exists():
        raise FileNotFoundError(
            f"CRE プロファイルが見つかりません: {profile_path}"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_cre_system_prompt(
    cre_profile: dict[str, Any],
    filter_type: str,
) -> str:
    """filter_type に応じて CRE 注入済みシステムプロンプトを構築する。

    filter_type の意味（mr_t_cognitive_profile.yaml の optimal_filters に対応）:
        "C" 堅実型 (hit_rate≈0.583): 「絞」「獲りやすさ」「資金稼ぎ」→ 的中率重視・軸1名
        "B" 穴狙い型 (hit_rate≈0.179): 「高配当」「大穴」「波乱」「妙味」「伏兵」→ 高回収率狙い
        "A" 標準型 (hit_rate≈0.244): 両パターンをバランスよく注入

    reverse_indicator_patterns（「自信」「見えた」「鉄板」等）は全 filter_type 共通で
    「見送りシグナル」として注入する。

    Args:
        cre_profile: load_cre_profile() の戻り値
        filter_type: "A" / "B" / "C" のいずれか（大文字）

    Returns:
        CRE 情報を注入したシステムプロンプト文字列

    Raises:
        ValueError: filter_type が "A" / "B" / "C" 以外の場合
    """
    filter_type = filter_type.upper()
    if filter_type not in ("A", "B", "C"):
        raise ValueError(f"filter_type は 'A' / 'B' / 'C' のいずれかです: {filter_type!r}")

    high_patterns: list = cre_profile.get("high_recovery_patterns", [])
    reverse_patterns: list = cre_profile.get("reverse_indicator_patterns", [])
    predictor_name: str = cre_profile.get("predictor_name", "AI 予想師")
    basic_stats: dict = cre_profile.get("basic_stats", {})

    # ─── filter 別キーワード選別 ───────────────────────────────────────
    _SOLID_KEYWORDS = {"絞", "獲りやすさ", "資金稼ぎ", "盤石"}
    _HOLE_KEYWORDS  = {"高配当", "大穴", "波乱", "妙味", "伏兵"}

    if filter_type == "C":
        target_keywords = _SOLID_KEYWORDS
        strategy_note = (
            "【堅実型フィルター】絞れるレース。的中率重視で軸を1名に絞り込め。\n"
            "3連単2〜3点の少点数勝負を優先する。"
        )
    elif filter_type == "B":
        target_keywords = _HOLE_KEYWORDS
        strategy_note = (
            "【穴狙い型フィルター】荒れる可能性あり。伏兵を含めて相手を広くとれ。\n"
            "高回収率狙いで3連複ながし・ワイドを優先する。"
        )
    else:  # filter_type == "A"
        target_keywords = _SOLID_KEYWORDS | _HOLE_KEYWORDS
        strategy_note = (
            "【標準型フィルター】中穴ゾーン。軸1名＋相手4名でバランスよく。\n"
            "堅実系と穴狙い系の両方を均等に考慮し、期待配当2〜5万円を目安にする。"
        )

    # ─── 高収益パターンを抽出してフォーマット ─────────────────────────
    selected_patterns = [
        p for p in high_patterns
        if any(kw in str(p.get("keyword", "")) for kw in target_keywords)
    ]

    pattern_lines: list[str] = []
    for p in selected_patterns:
        kw   = p.get("keyword", "")
        hr   = p.get("hit_rate")
        rr   = p.get("recovery_rate")
        examples: list = p.get("examples", [])

        line = f"  ・「{kw}」"
        if hr is not None:
            line += f"（的中率 {hr:.1%}"
        if rr is not None:
            line += f" / 回収率 {rr:.1%}）"
        elif hr is not None:
            line += "）"

        interp = p.get("interpretation", "")
        if interp:
            # interpretation が複数行の場合は先頭行のみ使う
            first_line = str(interp).strip().splitlines()[0]
            line += f"\n    → {first_line}"

        if examples:
            ex_str = " / ".join(f'「{e}」' for e in examples[:2])
            line += f"\n    例: {ex_str}"

        pattern_lines.append(line)

    patterns_text = "\n".join(pattern_lines) if pattern_lines else "（該当パターンなし）"

    # ─── 逆指標（全 filter_type 共通） ───────────────────────────────
    reverse_lines: list[str] = []
    for p in reverse_patterns:
        kw  = p.get("keyword", "")
        rr  = p.get("recovery_rate")
        hr  = p.get("hit_rate")
        interp = p.get("interpretation", "")

        line = f"  ✗「{kw}」"
        if rr is not None and hr is not None:
            line += f"（的中率 {hr:.1%} / 回収率 {rr:.1%}）"

        first_interp = str(interp).strip().splitlines()[0] if interp else ""
        if first_interp:
            line += f" → {first_interp}"

        reverse_lines.append(line)

    reverse_text = "\n".join(reverse_lines) if reverse_lines else "（データなし）"

    # ─── 基本統計サマリー ─────────────────────────────────────────────
    total = basic_stats.get("total_predictions", "?")
    hit_r = basic_stats.get("hit_rate", "?")
    rec_r = basic_stats.get("recovery_rate", "?")
    hit_r_str = f"{hit_r:.1%}" if isinstance(hit_r, float) else str(hit_r)
    rec_r_str = f"{rec_r:.1%}" if isinstance(rec_r, float) else str(rec_r)

    # ─── 会場別得意度（llm_instructions 注入 cmd_148k_sub3） ────────────
    strengths_data: dict = cre_profile.get("strengths", {})
    venue_list: list = strengths_data.get("venues", [])
    venue_lines: list[str] = []
    for v in venue_list:
        vname = v.get("name", "")
        vrr   = v.get("recovery_rate")
        if vname and vrr is not None:
            venue_lines.append(f"  ・{vname}（回収率 {vrr:.2f}）")
    venue_text = "\n".join(venue_lines) if venue_lines else ""

    # ─── llm_instructions（mr_t.yaml の 5ルール等を注入） ───────────────
    llm_instructions: str = str(cre_profile.get("llm_instructions", "")).strip()

    # ─── 会場別得意度セクション（データがある場合のみ） ──────────────────
    venue_section = (
        f"## 会場別得意度（積極的に狙うべき会場）\n"
        f"{venue_text}\n\n"
    ) if venue_text else ""

    # ─── llm_instructions セクション（指示がある場合のみ） ────────────────
    instructions_section = (
        f"## 追加指示（予想師固有ルール）\n"
        f"{llm_instructions}\n\n"
    ) if llm_instructions else ""

    return (
        f"あなたは予想師「{predictor_name}」の認知パターンを模倣する予想 AI です。\n"
        f"以下の CRE（認知逆エンジニアリング）プロファイルに従って分析を行ってください。\n\n"
        f"## 基本統計（参考）\n"
        f"  総予想数: {total}件 / 的中率: {hit_r_str} / 回収率: {rec_r_str}\n\n"
        f"## 戦略指針\n"
        f"{strategy_note}\n\n"
        f"{venue_section}"
        f"## 採用すべき高収益シグナル\n"
        f"{patterns_text}\n\n"
        f"## ⚠ 絶対見送りシグナル（これらを感じたら無条件スキップ）\n"
        f"{reverse_text}\n\n"
        f"{instructions_section}"
        f"## 出力形式\n"
        f"以下のフォーマットで必ず回答してください:\n"
        f"  軸: [選手/艇番]\n"
        f"  相手: [選手/艇番リスト]\n"
        f"  買い目: [具体的な購入方法]\n"
        f"  根拠: [200字以内]\n"
    )


# ─── プロンプトテンプレート ──────────────────────────────────────────────

def load_prompt_template(config_dir: str, sport: str) -> Optional[str]:
    """config/{sport}/{sport}_prompt.txt を読み込む。

    Args:
        config_dir: config ディレクトリのパス（例: "config"）
        sport: 競技種別文字列（例: "kyotei", "keirin"）

    Returns:
        テンプレート文字列。ファイルが存在しない場合は None。
    """
    path = Path(config_dir) / sport / f"{sport}_prompt.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _extract_template_section(template: str, tag: str) -> str:
    """テンプレートから [TAG]...[/TAG] セクションを抽出する。

    Args:
        template: テンプレート全文
        tag: セクションタグ名（例: "SYSTEM", "USER"）

    Returns:
        タグ内のテキスト。見つからない場合は空文字列。
    """
    pattern = re.compile(
        rf"\[{tag}\](.*?)\[/{tag}\]",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(template)
    return m.group(1).strip() if m else ""


def _build_entries_table_keirin(entries: list[dict[str, Any]]) -> str:
    """競輪出走表テーブルを Markdown 形式に変換する。

    keirin_prompt.txt の {entries_table} 変数に対応する。
    フォーマット: | 枠番 | 選手名 | 登録番号 | 級班 | 脚質 | 競走得点 | ライン構成 | 直近成績（5走） |

    Args:
        entries: レースデータの entries リスト

    Returns:
        Markdown テーブル文字列
    """
    if not entries:
        return "（出走表データなし）"

    rows: list[str] = []
    for e in entries:
        car_no    = e.get("car_no", "?")
        name      = e.get("name", "-")
        reg_no    = e.get("registration_number", "-")
        grade     = e.get("grade", "-")
        leg_type  = e.get("leg_type", "-")
        score     = e.get("competitive_score", e.get("score", e.get("win_rate")))
        score_str = f"{score:.2f}" if isinstance(score, float) else str(score) if score is not None else "-"
        line_info = e.get("line_info", "-")
        recent    = e.get("recent_results", "-")
        if isinstance(recent, list):
            recent = "/".join(str(r) for r in recent[:5])

        rows.append(
            f"| {car_no} | {name} | {reg_no} | {grade} | {leg_type} "
            f"| {score_str} | {line_info} | {recent} |"
        )

    # keirin_prompt.txt のテンプレートにヘッダー行とセパレーターが既に含まれるため
    # {entries_table} にはデータ行のみを返す（二重ヘッダーを防ぐ）
    return "\n".join(rows) if rows else "（出走表データなし）"


def _generate_line_formation(entries: list[dict[str, Any]]) -> str:
    """entries の脚質情報からライン構成サマリーテキストを自動生成する。

    車番と脚質を並べて表示する。line_info が存在する場合はそちらを優先する。

    Args:
        entries: レースデータの entries リスト

    Returns:
        ライン構成サマリー文字列（例: "1番: 逃げ / 2番: 捲り / 3番: 差し"）
    """
    if not entries:
        return "（データなし）"

    parts: list[str] = []
    for e in entries:
        car_no   = e.get("car_no", "?")
        leg_type = e.get("leg_type", "-")
        line_info = e.get("line_info", "")
        if line_info and line_info != "-":
            parts.append(f"{car_no}番({leg_type}/{line_info})")
        else:
            parts.append(f"{car_no}番: {leg_type}")

    return " / ".join(parts)


def _build_entries_table_kyotei(entries: list[dict[str, Any]]) -> str:
    """競艇出走表エントリーリストを Markdown テーブル形式に変換する。

    kyotei_prompt.txt の {entries_table} 変数に対応する。

    Args:
        entries: KyoteiScraper.fetch_entries() の戻り値リスト

    Returns:
        Markdown テーブル文字列
    """
    rows: list[str] = []
    for e in entries:
        boat_no  = e.get("boat_number", "?")
        name     = e.get("racer_name", "-")
        reg_no   = e.get("registration_number", "-")
        grade    = e.get("racer_class", "-")
        weight   = e.get("weight_kg")
        f_count  = e.get("false_start_count", 0)
        motor_wr = e.get("motor_win_rate")
        boat_wr  = e.get("boat_win_rate")
        avg_st   = e.get("avg_start_timing")
        course_stats: dict = e.get("course_stats", {})

        weight_str   = f"{weight:.1f}" if weight is not None else "-"
        motor_wr_str = f"{motor_wr:.2f}" if motor_wr is not None else "-"
        boat_wr_str  = f"{boat_wr:.2f}"  if boat_wr  is not None else "-"
        avg_st_str   = f"{avg_st:.2f}"   if avg_st   is not None else "-"

        course_str = " ".join(
            f"{c}コース:{rate:.0%}" for c, rate in sorted(course_stats.items())
        ) or "-"

        rows.append(
            f"| {boat_no} | {name} | {reg_no} | {grade} | {weight_str} "
            f"| {f_count} | {motor_wr_str} | {boat_wr_str} | {avg_st_str} | {course_str} |"
        )

    header = (
        "| 艇番 | 選手名 | 登番 | 級 | 体重 | F数 | "
        "モーター勝率 | ボート勝率 | ST平均 | コース別成績 |"
    )
    separator = "|------|--------|------|-----|------|-----|------------|-----------|--------|------------|"
    return "\n".join([header, separator] + rows) if rows else "（出走表データなし）"


def _render_template(
    template: str,
    cre_prompt: str,
    race_data: dict[str, Any],
    sport: str = "kyotei",
) -> tuple[str, str]:
    """テンプレートの SYSTEM / USER セクションに変数を埋め込む。

    Args:
        template: load_prompt_template() の戻り値
        cre_prompt: build_cre_system_prompt() の戻り値
        race_data: レースデータ辞書
        sport: 競技種別 ("keirin" or "kyotei")。entries_table の生成方式を切り替える

    Returns:
        (system_prompt, user_prompt) のタプル
    """
    system_raw = _extract_template_section(template, "SYSTEM")
    user_raw   = _extract_template_section(template, "USER")

    entries = race_data.get("entries", [])

    # sport別 entries_table 構築
    if sport == "keirin":
        entries_table = _build_entries_table_keirin(entries)
    else:
        entries_table = _build_entries_table_kyotei(entries)

    # 展示タイム（競艇固有）
    exhibition_times = race_data.get("exhibition_times", "-")
    if isinstance(exhibition_times, list):
        exhibition_times = "\n".join(
            f"  {et.get('boat_number', '?')}艇: {et.get('exhibition_time', '-')}秒"
            f"（チルト: {et.get('tilt', '-')}）"
            for et in exhibition_times
        )

    # ── 競輪固有変数の解決 ──────────────────────────────────────────────
    # bank_length: race_data優先、なければ400m相当
    bank_length_raw = race_data.get("bank_length", 400)
    bank_length_str = str(bank_length_raw).replace("m", "")
    _BANK_TENDENCY = {
        "333": "小バンク（まくり不利・逃げ有利）",
        "400": "標準バンク（展開次第でどの脚質も有利）",
        "500": "大バンク（まくり有効・スピード勝負）",
    }
    bank_tendency = _BANK_TENDENCY.get(bank_length_str, "標準バンク（展開次第）")

    # line_formation: race_data にあればそれを使用、なければ entries から自動生成
    line_formation = str(race_data.get("line_formation") or _generate_line_formation(entries))

    # race_date: keirin fixture では "date" キー、kyotei では "race_date"
    race_date = str(race_data.get("race_date") or race_data.get("date") or "-")

    # race_num: keirin では "race_no"(str)、kyotei では "race_num"(int)
    race_num = str(race_data.get("race_num") or race_data.get("race_no") or "-")

    # stage: keirin固有（特選/二次予選/準決勝/決勝等）
    stage = str(race_data.get("stage", "-"))

    # player_name: 予想師が予測するため未確定。プレースホルダー除去用デフォルト
    player_name = str(race_data.get("player_name", "（予想師が選択）"))

    variables: dict[str, str] = {
        # 共通変数
        "cre_profile_text":              cre_prompt,
        "venue_name":                    str(race_data.get("venue_name", "-")),
        "venue_code":                    str(race_data.get("venue_code", "-")),
        "grade":                         str(race_data.get("grade", "-")),
        "entries_table":                 entries_table,
        "additional_context":            str(race_data.get("additional_context", "-")),
        "filter_type":                   str(race_data.get("_filter_type", "-")),
        "race_date":                     race_date,
        "race_num":                      race_num,
        # 競輪固有変数
        "bank_length":                   bank_length_str,
        "bank_tendency":                 bank_tendency,
        "line_formation":                line_formation,
        "stage":                         stage,
        "player_name":                   player_name,
        # 競艇固有変数
        "venue_water_type":              str(race_data.get("venue_water_type", "-")),
        "venue_water_characteristic":    str(race_data.get("venue_water_characteristic", "-")),
        "wind_speed_ms":                 str(race_data.get("wind_speed_ms", "-")),
        "temperature_celsius":           str(race_data.get("temperature_celsius", "-")),
        "exhibition_times":              str(exhibition_times),
        # フォールバック
        "race_data":                     str(race_data),
    }

    # {変数名} を置換（コメント行 # ... は置換しない）
    def replace_vars(text: str) -> str:
        for key, val in variables.items():
            text = text.replace("{" + key + "}", val)
        return text

    system_prompt = replace_vars(system_raw)
    user_prompt   = replace_vars(user_raw)

    return system_prompt, user_prompt


# ─── メイン予想生成関数 ──────────────────────────────────────────────────

def generate_prediction(
    race_data: dict[str, Any],
    predictor_profile: dict[str, Any],
    config: dict[str, Any],
    filter_type: str = "A",
    sport: str = "keirin",
) -> str:
    """CRE 統合版 レース予想テキスト生成関数。

    Args:
        race_data: レース情報辞書。
            競輪: venue_name, race_no, grade, entries (car_no/name/grade/win_rate)
            競艇: venue_name, venue_code, race_num, grade, entries (boat_number/racer_name等),
                  venue_water_type, venue_water_characteristic,
                  exhibition_times, wind_speed_ms, temperature_celsius,
                  additional_context, race_date
        predictor_profile: 予想師プロファイル辞書。name, style, strengths を含む。
            CRE プロファイルが存在しない場合のフォールバックに使用する。
        config: 設定辞書。以下のキーを参照する:
            - config["llm"]["model"]        : Claude モデル名
            - config["llm"]["max_tokens"]   : 最大トークン数（デフォルト 512）
            - config["llm"]["temperature"]  : 温度（デフォルト 0.7）
            - config["pipeline"]["config_dir"] : config ディレクトリ（デフォルト "config"）
            - config["pipeline"]["cre_profile_path"] : CRE プロファイルパス（省略可）
            - config["dry_run"]             : True の場合 API 呼び出しをスキップ
        filter_type: CRE フィルタータイプ。"A"（標準）/ "B"（穴狙い）/ "C"（堅実）
        sport: 競技種別。"keirin"（競輪）/ "kyotei"（競艇）

    Returns:
        予想テキスト文字列。dry_run=True の場合は識別文字列を返す。

    Raises:
        EnvironmentError: ANTHROPIC_API_KEY 環境変数が未設定の場合
        anthropic.APIError: API 呼び出し失敗時
        KeyError: config["llm"]["model"] が存在しない場合
    """
    venue     = race_data.get("venue_name", race_data.get("venue", "不明"))
    race_no   = race_data.get("race_no", race_data.get("race_num", "?"))

    # ─── dry-run モード ────────────────────────────────────────────────
    if config.get("dry_run", False):
        return (
            f"[DRY-RUN] CRE統合 predictor "
            f"({venue} {race_no}R, filter={filter_type}, sport={sport})"
        )

    # ─── API キー確認 ─────────────────────────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # ─── LLM 設定 ──────────────────────────────────────────────────────
    model      = config["llm"]["model"]
    max_tokens = config.get("llm", {}).get("max_tokens", 512)
    # filter_type 別 temperature（cmd_148k_sub3: 0.7→最適値に変更 / cmd_149k_sub6: W-1/W-2修正）
    # 優先順位: temperature_by_filter[filter_type] > config.temperature > _DEFAULT_TEMP_BY_FILTER[filter_type] > 0.4
    # CHECK-7b: C型（堅実）=0.3（再現性重視）/ A型（標準）=0.4 / B型（穴狙い）=0.5（多様性許容）
    _DEFAULT_TEMP_BY_FILTER = {"C": 0.3, "A": 0.4, "B": 0.5}
    _temp_by_filter: dict = config.get("llm", {}).get("temperature_by_filter", {})
    _filter_temp = _temp_by_filter.get(filter_type)
    if _filter_temp is not None:
        # W-1修正: _DEFAULT_TEMP_BY_FILTER をフォールバックとして実際に使用
        # W-2修正: or 演算子を is not None パターンに変更（temperature=0.0 の誤処理防止）
        temperature = _filter_temp
    else:
        _config_temp = config.get("llm", {}).get("temperature")
        temperature = _config_temp if _config_temp is not None else _DEFAULT_TEMP_BY_FILTER.get(filter_type, 0.4)

    # ─── config_dir 解決 ─────────────────────────────────────────────
    config_dir = config.get("pipeline", {}).get("config_dir", "config")

    # ─── プロンプト構築 ───────────────────────────────────────────────
    template = load_prompt_template(config_dir, sport)

    if template is not None:
        # テンプレートが存在する場合: CRE 統合プロンプトを構築
        cre_profile_path = config.get("pipeline", {}).get("cre_profile_path")

        if cre_profile_path:
            cre_profile = load_cre_profile(cre_profile_path)
            cre_text = build_cre_system_prompt(cre_profile, filter_type)
        else:
            # CRE プロファイルパス未設定時はデフォルトプロファイルテキストを抽出
            cre_text = _extract_template_section(template, "DEFAULT_CRE_PROFILE")
            if not cre_text:
                cre_text = _build_system_prompt(predictor_profile)

        # race_data に filter_type を埋め込む（テンプレート変数 {filter_type} 用）
        race_data_with_filter = {**race_data, "_filter_type": filter_type}
        system_prompt, user_prompt = _render_template(template, cre_text, race_data_with_filter, sport=sport)

    else:
        # テンプレートが存在しない場合: 後方互換フォールバック
        system_prompt = _build_system_prompt(predictor_profile)
        user_prompt   = _build_user_prompt(race_data)

    # ─── code_agent モード（APIキーなし時の足軽委任） ─────────────────
    if not api_key:
        return _request_code_agent_prediction(
            venue, race_no, system_prompt, user_prompt, filter_type, sport, config,
        )

    # ─── Claude API 呼び出し ──────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=temperature,
    )
    return message.content[0].text


# ─── code_agent モード（Claude Code 足軽による予測委任） ─────────────────

_CODE_AGENT_DIR = Path(__file__).resolve().parent.parent / "queue" / "predictions"


def _request_code_agent_prediction(
    venue: str,
    race_no: str,
    system_prompt: str,
    user_prompt: str,
    filter_type: str,
    sport: str,
    config: dict[str, Any],
) -> str:
    """APIキーがない場合、Claude Code足軽にYAML経由で予測を委任する。

    1. queue/predictions/requests/ にリクエストYAMLを書き出す
    2. queue/predictions/results/ に結果が書き込まれるのを待つ（最大5分）
    3. 結果の prediction_text を返す

    足軽側は queue/predictions/requests/ を監視し、
    system_prompt + user_prompt をもとに予測テキストを生成して
    queue/predictions/results/{task_id}.yaml に書き込む。
    """
    import logging
    logger = logging.getLogger(__name__)

    req_dir = _CODE_AGENT_DIR / "requests"
    res_dir = _CODE_AGENT_DIR / "results"
    req_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    task_id = f"pred_{sport}_{venue}_{race_no}"
    req_file = req_dir / f"{task_id}.yaml"
    res_file = res_dir / f"{task_id}.yaml"

    # 古い結果ファイルを削除
    if res_file.exists():
        res_file.unlink()

    # リクエスト書き出し
    request = {
        "task_id": task_id,
        "status": "pending",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "venue": venue,
        "race_no": race_no,
        "sport": sport,
        "filter_type": filter_type,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }
    req_file.write_text(yaml.dump(request, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    logger.info("[code_agent] リクエスト書き出し: %s", req_file)

    # 結果待ち（最大300秒 = 5分）
    timeout = config.get("code_agent", {}).get("timeout_sec", 300)
    poll_interval = 2
    elapsed = 0
    while elapsed < timeout:
        if res_file.exists():
            result = yaml.safe_load(res_file.read_text(encoding="utf-8"))
            if result and result.get("status") == "done":
                prediction_text = result.get("prediction_text", "")
                logger.info("[code_agent] 結果受信: %s (%d字)", task_id, len(prediction_text))
                return prediction_text
        time.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(
        f"[code_agent] {task_id} のレスポンスが{timeout}秒以内に得られませんでした。"
        f"足軽が queue/predictions/results/{task_id}.yaml に書き込んでいるか確認してください。"
    )


# ─── 後方互換用プライベート関数（既存コードから変更なし） ───────────────

def _build_system_prompt(profile: dict[str, Any]) -> str:
    """予想師プロファイルをもとにシステムプロンプトを構築する（後方互換）。"""
    name       = profile.get("name", "AI予想師")
    style      = profile.get("style", "データ重視")
    strengths  = profile.get("strengths", [])
    strengths_text = "、".join(strengths) if strengths else "ライン分析"

    return (
        f"あなたは競輪予想師「{name}」です。\n"
        f"予想スタイル: {style}\n"
        f"得意分野: {strengths_text}\n\n"
        "出走表データをもとに、軸選手（本命）と相手選手を選び、"
        "推奨買い目と根拠を簡潔に説明してください。"
    )


def _build_user_prompt(race_data: dict[str, Any]) -> str:
    """レースデータをもとにユーザープロンプトを構築する（後方互換）。"""
    venue   = race_data.get("venue_name", "不明")
    race_no = race_data.get("race_no", "?")
    grade   = race_data.get("grade", "?")
    entries = race_data.get("entries", [])

    entries_text = "\n".join(
        f"  {e.get('car_no', '?')}番: {e.get('name', '不明')} "
        f"(S{e.get('grade', '?')} / 勝率{e.get('win_rate', 0):.1%})"
        for e in entries
    )

    return (
        f"【{venue} {race_no}R】グレード: {grade}\n\n"
        f"出走選手:\n{entries_text}\n\n"
        "軸選手・相手・推奨買い目・根拠を述べてください。"
    )
