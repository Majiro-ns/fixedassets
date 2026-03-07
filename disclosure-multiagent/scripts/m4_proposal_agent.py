"""
Phase 1-M4: 松竹梅提案エージェント
disclosure-multiagent — m4_proposal_agent.py

## 概要
M3ギャップ分析の出力（GapItem）を受け取り、
法令要件に対応した「松」「竹」「梅」3水準の有報記載文案を生成する。

## 使い方
    # モックモード（ANTHROPIC_API_KEY 不要）
    USE_MOCK_LLM=true python3 scripts/m4_proposal_agent.py

    # 実LLMモード
    ANTHROPIC_API_KEY=sk-... python3 scripts/m4_proposal_agent.py

## 設計書
    10_Research/matsu_take_ume_design.md (subtask_063a5 / ashigaru4 作成)

## 依存
    anthropic>=0.40.0  (requirements_poc.txt 参照)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

# anthropic はモジュールレベルで import（unittest.mock.patch でパッチ可能にするため）
# ANTHROPIC_API_KEY 未設定・USE_MOCK_LLM=true の場合は実際には呼ばれない
try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

# ------------------------------------------------------------------
# 定数（設計書 Section M4-2 準拠）
# ------------------------------------------------------------------

VALID_LEVELS = ("松", "竹", "梅")
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
MAX_REGENERATE = 2  # 品質チェック失敗時の最大再生成回数

# 開示レベル別文字数制限（設計書 M4-3 CHAR_LIMITS）
CHAR_LIMITS: dict[str, dict[str, int]] = {
    "梅": {"min": 50,  "max": 120, "target": 80},
    "竹": {"min": 100, "max": 260, "target": 150},  # 設計書 100〜200字+30%バッファ（few-shot例が240字台のため）
    "松": {"min": 200, "max": 480, "target": 300},
}

# 禁止パターン（設計書 M4-3 FORBIDDEN_PATTERNS）
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"第\d+条", "法令条文の直接引用（「第○○条」）"),
    (r"第\d+項", "法令条文の直接引用（「第○○項」）"),
    (r"内閣府令第\d+号", "内閣府令番号の直接引用"),
    (r"株式会社[^\s。、「」（）]{2,10}(?=\s|。|、)", "特定企業名の記載"),
    (r"(?<![Ee\[])\d{4,6}千円(?!])", "具体的な給与金額（プレースホルダ使用を推奨）"),
    (r"必ず(?!プレースホルダ)", "断言表現「必ず」"),
    (r"絶対に?", "断言表現「絶対」"),
    (r"業界(?:トップ|No\.?1|一位)", "根拠のない業界比較"),
    (r"保証(?:いたし|し|する|します)", "保証表現"),
]

PLACEHOLDER_PATTERN = re.compile(r'\[[^\]]{1,30}\]')

# ------------------------------------------------------------------
# データクラス定義
# ------------------------------------------------------------------

@dataclass
class GapItem:
    """
    M3ギャップ分析エージェントの出力スキーマ（入力インターフェース）。
    gap_analysis_design.md の gaps[*] 要素に対応。
    """
    gap_id: str                     # 例: "GAP-001"
    section_id: str                 # 例: "HC-001"
    section_heading: str            # 例: "e. 人的資本経営に関する指標"
    change_type: str                # "追加必須" / "修正推奨" / "参考"
    has_gap: bool                   # True = ギャップあり
    disclosure_item: str            # 例: "平均年間給与の対前事業年度増減率"
    reference_law_id: str           # 例: "HC_20260220_001"
    reference_law_title: str        # 例: "企業内容等の開示に関する内閣府令改正..."
    reference_url: str              # 例: "https://sustainablejapan.jp/..."
    source_confirmed: bool          # source_confirmed: true/false
    source_warning: Optional[str] = None   # source_confirmed: false の場合の警告
    gap_description: Optional[str] = None  # ギャップの説明
    evidence_hint: Optional[str] = None    # 判定根拠テキスト
    law_summary: Optional[str] = None      # 法令エントリの summary（プロンプト用）


@dataclass
class QualityCheckResult:
    """品質チェック結果"""
    passed: bool
    should_regenerate: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    char_count: int = 0


@dataclass
class Proposal:
    """
    1水準（松/竹/梅）の提案文とメタデータ。
    """
    level: str                      # "松" / "竹" / "梅"
    text: str                       # 生成された文案テキスト
    quality: QualityCheckResult     # 品質チェック結果
    attempts: int = 1               # LLM呼び出し回数
    status: str = "pass"            # "pass" / "warn" / "fail"
    placeholders: list[str] = field(default_factory=list)  # 残存プレースホルダ


@dataclass
class ProposalSet:
    """
    1つの GapItem に対する 3水準（松竹梅）の提案セット。
    """
    gap_id: str
    disclosure_item: str
    reference_law_id: str
    reference_url: str
    source_warning: Optional[str]
    matsu: Proposal     # 松
    take: Proposal      # 竹
    ume: Proposal       # 梅

    def get_proposal(self, level: str) -> Proposal:
        if level == "松":
            return self.matsu
        elif level == "竹":
            return self.take
        elif level == "梅":
            return self.ume
        raise ValueError(f"無効なレベル: {level}。'松'/'竹'/'梅' のいずれかを指定してください。")

    def all_passed(self) -> bool:
        return all(p.status in ("pass", "warn") for p in [self.matsu, self.take, self.ume])


# ------------------------------------------------------------------
# few-shot 例（設計書 M4-1 記載例から引用）
# ------------------------------------------------------------------

FEW_SHOT_EXAMPLES: dict[str, dict[str, str]] = {
    "企業戦略と関連付けた人材戦略": {
        "松": (
            "当社は、「2030年ビジョン」に掲げる事業成長率15%の達成に向け、"
            "事業戦略と連動した人材戦略を「人材ポートフォリオ計画」として策定しています。"
            "デジタル変革（DX）推進を担う専門人材を2028年度末までに現状比2倍（300名）に拡充する計画の下、"
            "採用・育成・リスキリングの三本柱で体制整備を進めています。\n\n"
            "【目標・KPI（2026年度実績）】\n"
            "- デジタル専門人材数: 156名（計画比98%、前年比+23名）\n"
            "- リスキリング対象者: 従業員の35%（2025年度比+10ポイント）\n"
            "- 人材投資額: 1人当たり年間12.5万円（前年比+15%）\n\n"
            "なお、本人材戦略の進捗は、サステナビリティ委員会（四半期開催）で取締役会に報告し、"
            "外部機関による第三者保証の適用を2027年度より検討しています。"
        ),
        "竹": (
            "当社は、事業成長を支える人材基盤の強化を経営の最重要課題と位置付けています。"
            "中期経営計画（2024〜2026年度）において、デジタル・技術領域を中心とした専門人材の"
            "確保・育成を重点施策とし、採用・リスキリング・リテンションの三方向から対応しています。\n\n"
            "人材育成においては、OJTと集合研修を組み合わせた体系的なプログラムを整備しており、"
            "専門スキルの習得と次世代リーダーの育成を並行して推進しています。"
            "毎期の人事施策の見直しにより、人材戦略と事業戦略の整合性を継続的に確認しています。"
        ),
        "梅": (
            "当社は、持続的な企業価値向上に向け、事業戦略の実現に必要な人材の確保・育成・定着を"
            "人材戦略の基本方針としています。"
        ),
    },
    "平均年間給与の対前事業年度増減率": {
        "松": (
            "【平均年間給与の推移（連結・単体）】\n\n"
            "連結従業員の平均年間給与は[平均年間給与額]千円（前事業年度比[率]%）です。\n\n"
            "内訳: 正社員 [正社員給与]千円（[率]%）、嘱託・契約社員 [契約社員給与]千円（[率]%）\n\n"
            "算出方法: 「平均年間給与」は、決算期末の在籍者の1年間の給与・賞与・各種手当の"
            "合計を在籍者数で除して算出しています。"
            "育児休業・介護休業中の従業員を除外しています。\n\n"
            "部門別内訳（参考）:\n"
            "- 技術系職種: [技術職給与]千円\n"
            "- 管理系職種: [管理職給与]千円"
        ),
        "竹": (
            "連結従業員の平均年間給与は[平均年間給与額]千円（前事業年度比[率]%）です。\n\n"
            "算出方法: 決算期末在籍者の年間給与・賞与・手当合計を在籍者数で除した金額です。"
            "育児休業中の従業員は対象から除外しています。\n\n"
            "単体従業員の平均年間給与は[単体給与額]千円（前事業年度比[率]%）です。"
        ),
        "梅": (
            "連結従業員の平均年間給与は[平均年間給与額]千円（前事業年度比[率]%）です。"
            "単体従業員の平均年間給与は[単体給与額]千円（同[率]%）です。"
        ),
    },
    "従業員給与等の決定に関する方針": {
        "松": (
            "当社の給与水準は、職務の難易度・業績貢献・市場相場の三要素を基本に決定しています。\n\n"
            "[方針]\n"
            "1. ジョブ型人材マネジメントの段階的導入: 役割・職責に基づく報酬体系へ移行中\n"
            "2. 業績連動賞与: 会社業績・部門業績・個人評価の三層連動。上限は基本給の[上限率]%\n"
            "3. 賃上げ方針: [年度]年度より[N]年連続のベースアップを実施。物価上昇率との乖離を年次レビュー\n"
            "4. 市場比較: 毎年外部賃金調査と比較し、同業他社との競争力を確認\n"
            "5. ジェンダー平等: 同一職務・同一グレードでの男女間賃金格差ゼロを目標に推進中"
        ),
        "竹": (
            "当社の従業員給与は、職務の難易度・スキル・業績への貢献度、および市場相場を踏まえて"
            "決定しています。賞与は会社業績と個人評価を反映した連動制を採用しています。"
            "賃上げについては、物価動向・業績・同業他社の水準を勘案し、毎期見直しを行っています。"
        ),
        "梅": "当社の従業員給与は、職務・スキル・業績を踏まえ決定しています。",
    },
    "人材育成方針": {
        "松": (
            "当社は、「人を最重要の経営資源」と位置付け、全従業員の成長を支援する育成体系を"
            "構築しています。\n\n"
            "OJTを基盤としつつ、階層別・職能別の研修プログラムにより専門性と管理能力を体系的に"
            "高める仕組みを整備しています。\n\n"
            "主な取り組み:\n"
            "- リスキリング: オンライン学習プラットフォームを全従業員に開放（[年度]年度〜）\n"
            "- 1人当たり教育投資: 年間[投資額]万円（前年比[率]%増）\n"
            "- 次世代リーダー育成: 管理職候補者向け特別研修（年[N]名）"
        ),
        "竹": (
            "当社は、OJT（現場経験）を基本としつつ、役職・キャリアステージに応じた"
            "階層別研修プログラムを整備しています。管理職向けには外部講師によるリーダーシップ研修、"
            "一般従業員向けには技術研修・スキルアップ支援（資格取得補助制度）を提供しています。"
            "また、DX推進に向けたリスキリング支援として、オンライン学習プラットフォームを"
            "全従業員に開放しています。"
        ),
        "梅": "当社は、従業員の能力開発のため、階層別研修・OJT・資格取得支援を実施しています。",
    },
    "GHG排出量（Scope1・Scope2）の開示": {
        "松": (
            "【GHG排出量（2026年度実績）】\n\n"
            "Scope1（直接排出）: [Scope1排出量]t-CO2e（前年比[率]%）\n"
            "Scope2（間接排出・市場基準）: [Scope2市場基準排出量]t-CO2e\n"
            "Scope2（間接排出・立地基準）: [Scope2立地基準排出量]t-CO2e\n"
            "Scope1+2合計: [合計排出量]t-CO2e（前年比[率]%）\n\n"
            "【算定方法】\n"
            "GHGプロトコル「コーポレート基準」に準拠。排出係数は[係数データベース名]を使用。"
            "組織境界は財務管理アプローチを採用し、連結子会社[N]社を含む。\n\n"
            "【第三者検証】\n"
            "[検証機関名]による限定的保証を取得（検証基準: ISO14064-3）。"
        ),
        "竹": (
            "Scope1（直接排出）は[Scope1排出量]t-CO2e、Scope2（市場基準）は[Scope2排出量]t-CO2eです（前年比[率]%）。"
            "GHGプロトコル「コーポレート基準」に準拠して算定しており、"
            "連結グループ全体（[N]社）を対象としています。"
            "算定に使用した排出係数は[係数データベース名]に基づきます。"
        ),
        "梅": (
            "Scope1（直接排出）: [Scope1排出量]t-CO2e、"
            "Scope2（市場基準）: [Scope2排出量]t-CO2eです（GHGプロトコル準拠）。"
        ),
    },
    "GHG削減目標・進捗状況の開示": {
        "松": (
            "【GHG排出削減目標】\n\n"
            "当社は、[基準年度]年度比[削減率]%削減（[目標年度]年度）を目標に掲げています。"
            "中間目標として[中間年度]年度までに[中間削減率]%削減を設定しています。\n\n"
            "【[当年度]年度実績と進捗】\n"
            "Scope1+2排出量: [実績排出量]t-CO2e（基準年比[達成率]%削減）\n"
            "削減貢献量内訳:\n"
            "- 再生可能エネルギー導入: [再エネ削減量]t-CO2e\n"
            "- エネルギー効率改善: [効率改善削減量]t-CO2e\n"
            "- その他（オフセット等）: [その他削減量]t-CO2e\n\n"
            "目標の科学的根拠: SBTi（Science Based Targets initiative）認定を[取得済み/申請中]。"
        ),
        "竹": (
            "当社は[基準年度]年度比[削減率]%削減（[目標年度]年度）を目標とし、"
            "[当年度]年度実績は基準年比[達成率]%削減（[実績排出量]t-CO2e）です。"
            "再生可能エネルギー導入とエネルギー効率改善を主要施策として推進しています。"
        ),
        "梅": (
            "[基準年度]年度比[削減率]%削減（[目標年度]年度）を目標とし、"
            "[当年度]年度は[実績排出量]t-CO2e（基準年比[達成率]%削減）です。"
        ),
    },
    # ── 銀行業（バーゼルIII / 不良債権）few-shot examples ──
    "自己資本比率（CET1 / Tier1 / 総自己資本）の開示": {
        "松": (
            "【自己資本比率（2026年3月末・連結）】\n\n"
            "普通株式等Tier1比率（CET1比率）: [CET1比率]%（規制最低水準4.5%＋資本保全バッファー2.5%=7.0%に対し[超過分]%超過）\n"
            "Tier1比率: [Tier1比率]%（規制最低水準6.0%に対し[超過分]%超過）\n"
            "総自己資本比率: [総自己資本比率]%（規制最低水準8.0%に対し[超過分]%超過）\n\n"
            "リスク加重資産合計: [RWA合計]億円\n"
            "  うち信用リスク: [信用RWA]億円 / 市場リスク: [市場RWA]億円 / オペリスク: [オペRWA]億円\n\n"
            "単体自己資本比率: CET1 [単体CET1]% / Tier1 [単体Tier1]% / 総自己資本 [単体総自己]%\n\n"
            "前期（2025年3月末）比較: CET1比率 [前期CET1]% → [当期CET1]%（[増減]%ポイント）\n"
            "主な変動要因: 当期利益計上による内部留保増加、新規融資によるRWA増加"
        ),
        "竹": (
            "2026年3月末（連結）の自己資本比率は以下の通りです。\n\n"
            "CET1比率: [CET1比率]%、Tier1比率: [Tier1比率]%、総自己資本比率: [総自己資本比率]%\n\n"
            "バーゼルIII規制上の最低水準（CET1 4.5%+資本保全バッファー2.5%）を上回っており、"
            "十分な資本充実度を維持しています。"
            "リスク加重資産は[RWA合計]億円（前期比[増減率]%）です。"
        ),
        "梅": (
            "2026年3月末（連結）のCET1比率は[CET1比率]%、"
            "総自己資本比率は[総自己資本比率]%であり、バーゼルIII規制水準を充足しています。"
        ),
    },
    "不良債権残高・分類（金融再生法）の開示": {
        "松": (
            "【不良債権の状況（金融再生法ベース）2026年3月末・連結】\n\n"
            "| 分類 | 残高（億円） | 保全額 | 未保全残高 |\n"
            "|------|------------|--------|----------|\n"
            "| 破綻先債権 | [破綻先残高] | [保全額] | [未保全額] |\n"
            "| 実質破綻先債権 | [実質破綻残高] | [保全額] | [未保全額] |\n"
            "| 破綻懸念先債権 | [破綻懸念残高] | [保全額] | [未保全額] |\n"
            "| 要管理先債権 | [要管理残高] | [保全額] | [未保全額] |\n"
            "| 合計（不良債権） | [合計残高] | — | — |\n\n"
            "不良債権比率（対総与信）: [比率]%（前期[前期比率]%、[増減]%ポイント改善）\n\n"
            "保全率（担保・保証等による保全額/不良債権残高）: [保全率]%\n"
            "なお、引当・保全後の実質的な未保全残高は[実質未保全]億円です。"
        ),
        "竹": (
            "2026年3月末（連結）の不良債権残高（金融再生法ベース）は[合計残高]億円（前期比[増減]億円）です。\n\n"
            "内訳: 破綻先[破綻先残高]億円、実質破綻先[実質破綻残高]億円、"
            "破綻懸念先[破綻懸念残高]億円、要管理先[要管理残高]億円\n\n"
            "不良債権比率は[比率]%（前期[前期比率]%）で、"
            "担保・保証による保全率は[保全率]%です。"
        ),
        "梅": (
            "2026年3月末（連結）の不良債権残高（金融再生法ベース）は[合計残高]億円、"
            "不良債権比率は[比率]%です。"
        ),
    },
    "貸倒引当金計上方針の開示": {
        "松": (
            "当社グループは、与信先の信用リスクに応じて以下の方針で貸倒引当金を計上しています。\n\n"
            "【一般貸倒引当金】\n"
            "正常先および要注意先に対し、過去[N]年間の貸倒実績率を基礎に、"
            "現在の経済環境・マクロ経済見通し（GDP成長率・失業率等）を反映した"
            "フォワードルッキング調整を加味して算定します。\n\n"
            "【個別貸倒引当金】\n"
            "破綻懸念先以下の与信先に対し、担保・保証の処分可能見込額を控除した"
            "未保全残高を基礎として、回収可能性を個別に評価の上計上します。\n\n"
            "IFRS9予想信用損失（ECL）モデル採用に向け、3ステージ方式への段階的移行を検討中です。\n\n"
            "当期の貸倒引当金計上額: [当期繰入額]億円（一般[一般繰入]億円＋個別[個別繰入]億円）\n"
            "貸倒引当金残高: [引当残高]億円（うち一般[一般残高]億円、個別[個別残高]億円）"
        ),
        "竹": (
            "当社グループは、与信先の財務状況・返済能力に基づく内部格付けに応じ、"
            "一般貸倒引当金（正常先・要注意先向け）と個別貸倒引当金（破綻懸念先以下向け）を計上しています。\n\n"
            "一般貸倒引当金は過去の損失実績率にマクロ経済見通しを加味して算定し、"
            "個別貸倒引当金は担保・保証による保全後の未保全残高に基づき個別評価しています。\n\n"
            "当期末の貸倒引当金残高は[引当残高]億円です。"
        ),
        "梅": (
            "当社グループは、与信先の信用リスクに応じ一般貸倒引当金・個別貸倒引当金を計上しており、"
            "当期末残高は[引当残高]億円です。"
        ),
    },
    "気候変動に関するガバナンス体制の開示": {
        "松": (
            "【気候変動ガバナンス体制】\n\n"
            "取締役会は、気候変動をグループ全体の重要な経営リスク・機会と認識し、"
            "サステナビリティ委員会（[開催頻度]）を通じて定期的な報告・監督を実施しています。\n\n"
            "経営陣の役割:\n"
            "- [役職名]（委員長）が気候変動戦略の立案・執行を統括\n"
            "- 気候関連リスク・機会は[部門名]が一次管理し、[報告頻度]で経営会議に報告\n\n"
            "スキル・能力開発:\n"
            "- 取締役[N]名が気候変動・サステナビリティ関連の専門研修を修了\n"
            "- 役員報酬の[N]%を気候変動目標達成度に連動"
        ),
        "竹": (
            "取締役会は気候変動をグループの重要課題と位置付け、"
            "サステナビリティ委員会（[開催頻度]）を通じて気候関連リスク・機会の監督を行っています。"
            "[役職名]が気候変動戦略の執行責任を担い、重要な事項は取締役会に報告されます。"
        ),
        "梅": (
            "取締役会はサステナビリティ委員会を通じて気候変動リスク・機会を監督しています。"
            "[役職名]が気候変動対応の執行責任者です。"
        ),
    },
}

# セクション名マッチングのための正規化マッピング
SECTION_NORMALIZE: dict[str, str] = {
    "企業戦略と関連付けた人材戦略": "企業戦略と関連付けた人材戦略",
    "人材戦略": "企業戦略と関連付けた人材戦略",
    "企業戦略と人材戦略": "企業戦略と関連付けた人材戦略",
    "平均年間給与": "平均年間給与の対前事業年度増減率",
    "平均年間給与の対前事業年度増減率": "平均年間給与の対前事業年度増減率",
    "給与増減率": "平均年間給与の対前事業年度増減率",
    "給与決定方針": "従業員給与等の決定に関する方針",
    "従業員給与等の決定に関する方針": "従業員給与等の決定に関する方針",
    "給与方針": "従業員給与等の決定に関する方針",
    "人材育成方針": "人材育成方針",
    "人材育成": "人材育成方針",
    # SSBJ関連マッピング
    "GHG排出量": "GHG排出量（Scope1・Scope2）の開示",
    "GHG排出量（Scope1・Scope2）の開示": "GHG排出量（Scope1・Scope2）の開示",
    "Scope1排出量": "GHG排出量（Scope1・Scope2）の開示",
    "Scope2排出量": "GHG排出量（Scope1・Scope2）の開示",
    "温室効果ガス排出量": "GHG排出量（Scope1・Scope2）の開示",
    "GHG削減目標": "GHG削減目標・進捗状況の開示",
    "GHG削減目標・進捗状況の開示": "GHG削減目標・進捗状況の開示",
    "排出削減目標": "GHG削減目標・進捗状況の開示",
    "脱炭素目標": "GHG削減目標・進捗状況の開示",
    "気候変動ガバナンス": "気候変動に関するガバナンス体制の開示",
    "気候変動に関するガバナンス体制の開示": "気候変動に関するガバナンス体制の開示",
    "サステナビリティガバナンス": "気候変動に関するガバナンス体制の開示",
    "気候変動ガバナンス体制": "気候変動に関するガバナンス体制の開示",
    # 銀行業（バーゼルIII / 不良債権）マッピング
    "自己資本比率": "自己資本比率（CET1 / Tier1 / 総自己資本）の開示",
    "自己資本比率（CET1 / Tier1 / 総自己資本）の開示": "自己資本比率（CET1 / Tier1 / 総自己資本）の開示",
    "CET1比率": "自己資本比率（CET1 / Tier1 / 総自己資本）の開示",
    "バーゼルIII自己資本": "自己資本比率（CET1 / Tier1 / 総自己資本）の開示",
    "不良債権": "不良債権残高・分類（金融再生法）の開示",
    "不良債権残高": "不良債権残高・分類（金融再生法）の開示",
    "不良債権残高・分類（金融再生法）の開示": "不良債権残高・分類（金融再生法）の開示",
    "貸倒引当金": "貸倒引当金計上方針の開示",
    "貸倒引当金計上方針の開示": "貸倒引当金計上方針の開示",
    "引当金計上方針": "貸倒引当金計上方針の開示",
}

# ------------------------------------------------------------------
# システムプロンプト（設計書 M4-2 Section 3.1 準拠）
# ------------------------------------------------------------------

BASE_SYSTEM_PROMPT = """あなたは有価証券報告書（有報）の人的資本開示を専門とする実務アドバイザーです。
スタンダード上場企業の経理・IR担当者が実際に使える「過不足ない」記載文案を提案します。

## あなたの役割
- 法令・府令・金融庁ガイダンスに基づく記載義務を満たす文案を生成します
- ユーザーが選択した開示レベル（松/竹/梅）に応じた記載量・詳細度で提案します
- 実務担当者がそのまま、または最小限の修正で使用できる文案を目指します
- 法令条文の直接引用は行いません（「○○法第○○条」等の記載は不要です）

## 開示レベルの定義
- 松: KPI・数値目標・ガバナンス体制・第三者保証の言及を含む充実した記載
- 竹: 必須項目を過不足なく満たす実務的な記載（200字以内が目安）
- 梅: 法令義務の最小限を満たす簡潔な記載（100字以内が目安）

## 出力ルール
1. 選択されたレベルの提案文を1本のみ出力してください
2. 出力は文章のみ。説明・注釈・コメントは付けないでください
3. 固有の企業名・製品名・実在する数値（xxx千円等）はプレースホルダで表現してください
   - 例: [平均年間給与額]千円、[前年比増減率]%
4. 禁止事項:
   - 法令条文・府令条文の直接引用（「第○○条」の表記）
   - 保証できない断言表現（「必ず」「絶対に」等）
   - 根拠のない業界比較（「業界トップ水準」等）
5. 文字数目安:
   - 梅: 50〜100字
   - 竹: 100〜200字
   - 松: 200〜400字"""

USER_PROMPT_TEMPLATE = """\
## 開示変更項目

**セクション**: {section_name}
**変更種別**: {change_type}
**変更根拠**: {law_summary}
**根拠ID**: {law_id}

## 企業プロファイル

**開示レベル**: {level}

---

上記の変更項目について、{level}レベルの有報記載文案を1本作成してください。"""


# ------------------------------------------------------------------
# 品質チェック関数群（設計書 M4-3 準拠）
# ------------------------------------------------------------------

def check_char_count(text: str, level: str) -> tuple[bool, str, int]:
    """
    文字数チェック。

    Returns:
        (is_valid, reason, char_count)
    """
    if level not in CHAR_LIMITS:
        raise ValueError(f"無効なレベル: {level}。'松'/'竹'/'梅' のいずれかを指定してください。")
    char_count = len(text.strip())
    limits = CHAR_LIMITS[level]
    if char_count < limits["min"]:
        return False, f"文字数不足: {char_count}字（{level}の最小{limits['min']}字を下回る）", char_count
    if char_count > limits["max"]:
        return False, f"文字数超過: {char_count}字（{level}の最大{limits['max']}字を超過）", char_count
    return True, f"文字数OK: {char_count}字", char_count


def check_forbidden_patterns(text: str) -> list[dict]:
    """
    禁止パターンを検出する。

    Returns:
        list of {"pattern": str, "reason": str, "match": str}
    """
    violations = []
    for pattern, reason in FORBIDDEN_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            violations.append({
                "pattern": pattern,
                "reason": reason,
                "match": str(matches[:3]),
            })
    return violations


def check_placeholders(text: str) -> list[str]:
    """
    '[xxxxx]' 形式のプレースホルダ残存チェック。
    再生成は不要だが、ユーザーが数値を置換する必要がある箇所として通知する。
    """
    return PLACEHOLDER_PATTERN.findall(text)


def quality_check(text: str, level: str) -> QualityCheckResult:
    """
    文案の品質チェック（文字数 + 禁止パターン + プレースホルダ）。

    Returns:
        QualityCheckResult
    """
    if level not in VALID_LEVELS:
        raise ValueError(f"無効なレベル: {level}。'松'/'竹'/'梅' のいずれかを指定してください。")

    errors: list[str] = []
    warnings: list[str] = []

    # Step 1: 文字数チェック
    char_ok, char_msg, char_count = check_char_count(text, level)
    if not char_ok:
        errors.append(char_msg)

    # Step 2: 禁止パターンチェック
    violations = check_forbidden_patterns(text)
    for v in violations:
        errors.append(f"禁止パターン検出: {v['reason']} → {v['match']}")

    # Step 3: プレースホルダ確認（警告のみ）
    placeholders = check_placeholders(text)
    if placeholders:
        warnings.append(f"プレースホルダが残っています（要置換）: {placeholders}")

    should_regenerate = len(errors) > 0
    return QualityCheckResult(
        passed=not should_regenerate,
        should_regenerate=should_regenerate,
        warnings=warnings,
        errors=errors,
        char_count=char_count if char_ok or char_count > 0 else len(text.strip()),
    )


# ------------------------------------------------------------------
# プロンプト構築
# ------------------------------------------------------------------

def _normalize_section_name(section_name: str) -> str:
    """セクション名を正規化してfew-shot例のキーに合わせる。"""
    for key, normalized in SECTION_NORMALIZE.items():
        if key in section_name:
            return normalized
    return section_name


def build_system_prompt_with_few_shot(section_name: str, level: str) -> str:
    """
    セクション名とレベルに応じた few-shot 例を付加したシステムプロンプトを生成。

    Args:
        section_name: セクション名（部分一致でfew-shot例を選択）
        level: "松" / "竹" / "梅"

    Returns:
        システムプロンプト文字列
    """
    normalized = _normalize_section_name(section_name)
    if normalized in FEW_SHOT_EXAMPLES and level in FEW_SHOT_EXAMPLES[normalized]:
        example = FEW_SHOT_EXAMPLES[normalized][level]
        few_shot = f"\n\n## 参考例（{level}レベル — {normalized}）\n```\n{example}\n```"
        return BASE_SYSTEM_PROMPT + few_shot
    return BASE_SYSTEM_PROMPT


# ------------------------------------------------------------------
# LLM呼び出し
# ------------------------------------------------------------------

def _is_mock_mode() -> bool:
    """モックモードかどうかを判定。環境変数 USE_MOCK_LLM=true または ANTHROPIC_API_KEY 未設定。"""
    if os.environ.get("USE_MOCK_LLM", "").lower() == "true":
        return True
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return True
    return False


def _mock_generate(section_name: str, level: str) -> str:
    """モックモードでのテキスト生成。few-shot例をそのまま返す。"""
    normalized = _normalize_section_name(section_name)
    if normalized in FEW_SHOT_EXAMPLES and level in FEW_SHOT_EXAMPLES[normalized]:
        return FEW_SHOT_EXAMPLES[normalized][level]
    # フォールバック: レベル別のデフォルトテキスト
    defaults = {
        "松": (
            "当社は、経営戦略と連動した[セクション名]に関する方針を策定しています。"
            "具体的なKPI・数値目標を設定し、四半期ごとに取締役会へ進捗を報告する体制を整備しています。"
            "外部認証・第三者保証の取得についても検討を進めています。"
        ),
        "竹": (
            "当社は、[セクション名]に関する方針を経営計画と整合させ、"
            "継続的な改善に取り組んでいます。"
            "必要な指標の計測・開示を行い、担当部門による定期的な見直しを実施しています。"
        ),
        "梅": f"当社は、[セクション名]について、法令の定めに従い適切に対応しています。",
    }
    return defaults.get(level, f"【{level}レベル】[セクション名]に関する記載文案")


def generate_proposal(
    section_name: str,
    change_type: str,
    law_summary: str,
    law_id: str,
    level: str,
    system_prompt: Optional[str] = None,
) -> str:
    """
    指定レベルの有報記載文案を1件生成する。

    Args:
        section_name: セクション名
        change_type: "追加必須" / "修正推奨" / "参考"
        law_summary: 法令変更のサマリ
        law_id: 法令エントリID（例: "HC_20260220_001"）
        level: "松" / "竹" / "梅"
        system_prompt: 使用するシステムプロンプト（None の場合は自動構築）

    Returns:
        生成された文案テキスト
    """
    if level not in VALID_LEVELS:
        raise ValueError(f"無効なレベル: {level}。'松'/'竹'/'梅' のいずれかを指定してください。")

    if _is_mock_mode():
        return _mock_generate(section_name, level)

    # 実LLMモード
    if anthropic is None:
        raise ImportError("anthropic パッケージが未インストールです。pip install anthropic でインストールしてください。")

    if system_prompt is None:
        system_prompt = build_system_prompt_with_few_shot(section_name, level)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        section_name=section_name,
        change_type=change_type,
        law_summary=law_summary,
        law_id=law_id,
        level=level,
    )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip()


# ------------------------------------------------------------------
# 品質チェック付き文案生成
# ------------------------------------------------------------------

def generate_with_quality_check(
    section_name: str,
    change_type: str,
    law_summary: str,
    law_id: str,
    level: str,
) -> Proposal:
    """
    品質チェック付き文案生成。再生成を最大 MAX_REGENERATE 回まで試みる。

    Args:
        section_name, change_type, law_summary, law_id, level: generate_proposal と同じ

    Returns:
        Proposal データクラス
    """
    if level not in VALID_LEVELS:
        raise ValueError(f"無効なレベル: {level}。'松'/'竹'/'梅' のいずれかを指定してください。")

    system_prompt = build_system_prompt_with_few_shot(section_name, level)

    for attempt in range(1, MAX_REGENERATE + 2):  # 最大 MAX_REGENERATE+1 回
        text = generate_proposal(
            section_name, change_type, law_summary, law_id, level, system_prompt
        )
        qc = quality_check(text, level)
        placeholders = check_placeholders(text)

        if qc.passed:
            status = "warn" if qc.warnings else "pass"
            return Proposal(
                level=level,
                text=text,
                quality=qc,
                attempts=attempt,
                status=status,
                placeholders=placeholders,
            )

        # 最終試行でも失敗 → fail として返す
        if attempt > MAX_REGENERATE:
            return Proposal(
                level=level,
                text=text,
                quality=qc,
                attempts=attempt,
                status="fail",
                placeholders=placeholders,
            )

        # 再生成: エラー内容をプロンプトに追記
        error_feedback = "\n\n## 修正依頼\n以下の問題を修正してください:\n" + "\n".join(
            [f"- {e}" for e in qc.errors]
        )
        system_prompt = system_prompt + error_feedback

    # 到達不能だが型整合のため
    return Proposal(
        level=level,
        text="",
        quality=QualityCheckResult(passed=False, should_regenerate=True),
        attempts=MAX_REGENERATE + 1,
        status="fail",
    )


# ------------------------------------------------------------------
# メインエントリ: GapItem → ProposalSet
# ------------------------------------------------------------------

def generate_proposals(gap_item: GapItem) -> ProposalSet:
    """
    1つの GapItem から 松竹梅 3水準の提案セット（ProposalSet）を生成する。

    Args:
        gap_item: M3ギャップ分析エージェントの出力

    Returns:
        ProposalSet

    Raises:
        ValueError: gap_item.has_gap が False の場合（ギャップなし項目は提案不要）
    """
    if not gap_item.has_gap:
        raise ValueError(
            f"gap_id={gap_item.gap_id}: has_gap=False のため提案生成は不要です。"
            "ギャップがある項目（has_gap=True）のみ generate_proposals を呼び出してください。"
        )

    section_name = gap_item.disclosure_item or gap_item.section_heading
    law_summary = gap_item.law_summary or (
        f"{gap_item.reference_law_title}。{gap_item.change_type}の開示項目。"
    )

    proposals = {}
    for level in VALID_LEVELS:
        proposal = generate_with_quality_check(
            section_name=section_name,
            change_type=gap_item.change_type,
            law_summary=law_summary,
            law_id=gap_item.reference_law_id,
            level=level,
        )
        proposals[level] = proposal

    return ProposalSet(
        gap_id=gap_item.gap_id,
        disclosure_item=gap_item.disclosure_item,
        reference_law_id=gap_item.reference_law_id,
        reference_url=gap_item.reference_url,
        source_warning=gap_item.source_warning,
        matsu=proposals["松"],
        take=proposals["竹"],
        ume=proposals["梅"],
    )


# ------------------------------------------------------------------
# デモ実行
# ------------------------------------------------------------------

def _print_proposal_set(ps: ProposalSet) -> None:
    """ProposalSet の内容を表示する。"""
    print(f"\n{'='*60}")
    print(f"  GAP ID: {ps.gap_id}")
    print(f"  開示項目: {ps.disclosure_item}")
    print(f"  法令ID: {ps.reference_law_id}")
    if ps.source_warning:
        print(f"  ⚠️  {ps.source_warning}")
    print(f"{'='*60}")

    for level, proposal in [("松", ps.matsu), ("竹", ps.take), ("梅", ps.ume)]:
        icons = {"松": "🌲", "竹": "🎋", "梅": "🌸"}
        icon = icons.get(level, "")
        print(f"\n{icon} 【{level}】({proposal.status}, {proposal.quality.char_count}字, {proposal.attempts}回)")
        print("-" * 40)
        print(proposal.text)
        if proposal.placeholders:
            print(f"\n  ⚠️ 要置換: {proposal.placeholders}")
        if proposal.quality.errors:
            print(f"  ❌ エラー: {proposal.quality.errors}")
        if proposal.quality.warnings:
            print(f"  ⚠️ 警告: {proposal.quality.warnings}")


if __name__ == "__main__":
    print("\n=== M4 松竹梅提案エージェント デモ ===")
    print(f"モードP: {'モック (USE_MOCK_LLM=true または ANTHROPIC_API_KEY 未設定)' if _is_mock_mode() else '実LLM'}\n")

    # デモ用 GapItem（人材戦略 × HC_20260220_001）
    demo_gap = GapItem(
        gap_id="GAP-001",
        section_id="HC-001",
        section_heading="e. 人的資本経営に関する指標",
        change_type="追加必須",
        has_gap=True,
        disclosure_item="企業戦略と関連付けた人材戦略",
        reference_law_id="HC_20260220_001",
        reference_law_title="企業内容等の開示に関する内閣府令改正（人的資本開示拡充・給与開示）",
        reference_url="https://sustainablejapan.jp/2026/02/23/fsa-ssbj-4/122214",
        source_confirmed=True,
        law_summary="企業戦略と関連付けた人材戦略の記載が2026年3月期有報から必須となりました。経営戦略との連動を明示することが求められています。",
    )

    ps = generate_proposals(demo_gap)
    _print_proposal_set(ps)

    print(f"\n全提案通過: {ps.all_passed()}")
