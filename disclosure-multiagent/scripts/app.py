"""
app.py
======
disclosure-multiagent Phase 1-M5-2: Streamlit UI

設計書: report_integration_design.md M5-2 / 22_MVP_Development_Checklist.md M5-2
実装者: 足軽3 subtask_063a12
作成日: 2026-02-27

実行方法:
    cd scripts
    streamlit run app.py

Demo モード（PDFなし）:
    PDFをアップロードしないと、デモデータ（pipeline_mock）を使用して動作します。

本番モード（PDFあり）:
    PDF → M1.extract_report → M2.load_law_context → M3.analyze_gaps
         → M4.generate_proposals → M5.generate_report
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# スクリプトディレクトリを sys.path に追加（M1〜M5モジュールのインポート用）
_scripts_dir = Path(__file__).parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import streamlit as st  # noqa: E402


# ─────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────


def _is_api_key_available() -> bool:
    """ANTHROPIC_API_KEY が設定されているか確認"""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _ensure_mock_mode() -> None:
    """ANTHROPIC_API_KEY 未設定時にモックモード（USE_MOCK_LLM=true）を有効化"""
    if not _is_api_key_available():
        os.environ.setdefault("USE_MOCK_LLM", "true")


# ─────────────────────────────────────────────────────────
# パイプライン: Demo モード（PDF なし）
# ─────────────────────────────────────────────────────────


def run_demo_pipeline(
    company_name: str,
    fiscal_year: int,
    level: str,
    progress_bar,
    status_text,
) -> str:
    """
    Demo モード: PDFなしで pipeline_mock() を実行する。

    Args:
        company_name: 企業名（空の場合はデフォルト値を使用）
        fiscal_year:  対象年度
        level:        開示レベル ("松" / "竹" / "梅")
        progress_bar: st.progress オブジェクト
        status_text:  st.empty オブジェクト

    Returns:
        str: Markdown レポート
    """
    from m5_report_agent import pipeline_mock  # noqa: E402

    _ensure_mock_mode()

    status_text.text("📋 デモデータでレポートを生成中...")
    progress_bar.progress(30)

    report_md = pipeline_mock(
        company_name=company_name if company_name else "サンプル株式会社",
        fiscal_year=fiscal_year,
        level=level,
    )

    progress_bar.progress(100)
    status_text.text("✅ 完了！")
    return report_md


# ─────────────────────────────────────────────────────────
# パイプライン: フルモード（PDF あり）
# ─────────────────────────────────────────────────────────


def run_full_pipeline(
    pdf_bytes: bytes,
    fiscal_year: int,
    fiscal_month_end: int,
    level: str,
    company_name: str,
    progress_bar,
    status_text,
) -> str:
    """
    フルパイプライン: PDF → M1 → M2 → M3 → M4 → M5

    Args:
        pdf_bytes:        PDF ファイルのバイト列
        fiscal_year:      対象年度
        fiscal_month_end: 決算月（現在は3月のみ対応）
        level:            開示レベル
        company_name:     企業名（空の場合はPDFから自動抽出）
        progress_bar:     st.progress オブジェクト
        status_text:      st.empty オブジェクト

    Returns:
        str: Markdown レポート
    """
    from m1_pdf_agent import extract_report  # noqa: E402
    from m2_law_agent import load_law_context  # noqa: E402
    from m3_gap_analysis_agent import analyze_gaps  # noqa: E402
    from m4_proposal_agent import generate_proposals  # noqa: E402
    from m5_report_agent import generate_report, _m3_gap_to_m4_gap  # noqa: E402

    _ensure_mock_mode()

    # STEP 1: PDF解析（M1）
    status_text.text("📄 PDF解析中...")
    progress_bar.progress(10)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        structured_report = extract_report(
            pdf_path=tmp_path,
            fiscal_year=fiscal_year,
            fiscal_month_end=fiscal_month_end,
            company_name=company_name,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    progress_bar.progress(25)

    # STEP 2: 法令取得（M2）
    status_text.text("📚 法令情報を読み込み中...")
    law_context = load_law_context(
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
    )
    progress_bar.progress(40)

    # STEP 3: ギャップ分析（M3）
    status_text.text("🔍 ギャップ分析中...")
    gap_result = analyze_gaps(structured_report, law_context)
    progress_bar.progress(65)

    # STEP 4: 松竹梅提案生成（M4）— has_gap=True のギャップのみ
    status_text.text(f"✍️ {level}レベルの提案文を生成中...")
    proposals = []
    gap_items_with_gap = [g for g in gap_result.gaps if g.has_gap]
    for i, gap in enumerate(gap_items_with_gap):
        m4_gap = _m3_gap_to_m4_gap(gap)
        ps = generate_proposals(m4_gap)
        proposals.append(ps)
        # 進捗を 65%〜85% の間で更新
        pct = 65 + int(20 * (i + 1) / max(len(gap_items_with_gap), 1))
        progress_bar.progress(min(pct, 85))

    # STEP 5: レポート統合（M5）
    status_text.text("📋 レポートを生成中...")
    progress_bar.progress(90)
    report_md = generate_report(
        structured_report=structured_report,
        law_context=law_context,
        gap_result=gap_result,
        proposal_set=proposals,
        level=level,
    )
    progress_bar.progress(100)
    status_text.text("✅ 完了！")
    return report_md


# ─────────────────────────────────────────────────────────
# 入力バリデーション
# ─────────────────────────────────────────────────────────


def validate_inputs(fiscal_year: Optional[int], level: str, agreed: bool) -> list[str]:
    """バリデーション失敗時のエラーメッセージリストを返す。"""
    errors: list[str] = []
    if fiscal_year is None:
        errors.append("対象年度を選択してください")
    if not level:
        errors.append("開示レベル（松/竹/梅）を選択してください")
    if not agreed:
        errors.append("免責事項に同意してください")
    return errors


# ─────────────────────────────────────────────────────────
# 画面: アップロード
# ─────────────────────────────────────────────────────────


def render_upload() -> None:
    """アップロード画面を描画する。"""
    st.title("📋 開示変更レポート生成")
    st.caption(
        "有価証券報告書（公開済み）を入力すると、次期有報に必要な変更箇所を松竹梅で提案します。"
        " PDFを省略した場合はデモデータで動作します。"
    )

    with st.form("upload_form"):
        # ① PDFアップロード（任意 — 未アップロードは Demo モード）
        pdf_file = st.file_uploader(
            "有価証券報告書 PDF（任意。未アップロード時はデモデータを使用）",
            type=["pdf"],
            help="EDINETで取得した公開済み有報PDFをアップロードしてください（省略可）",
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            # ② 対象年度（必須）
            fiscal_year: int = st.selectbox(
                "対象年度（必須）",
                options=[2025, 2024, 2023],
                format_func=lambda y: f"{y}年度（{y}年4月〜{y + 1}年3月）",
            )
        with col2:
            # ③ 開示レベル — 松竹梅（必須）
            level: str = st.selectbox(
                "開示レベル（必須）",
                options=["竹", "松", "梅"],
                help=(
                    "竹: 必須項目を過不足なく満たす実務的な記載\n"
                    "梅: 法令義務の最小限を満たす簡潔な記載\n"
                    "松: KPI・数値目標・ガバナンス体制を含む充実した記載"
                ),
            )
        with col3:
            # ④ 企業名（任意）
            company_name: str = st.text_input(
                "企業名（任意）",
                placeholder="例: ○○株式会社",
            )

        # ⑤ 免責同意（必須）
        agreed: bool = st.checkbox(
            "**免責事項に同意します**: "
            "本レポートは参考情報です。最終判断は専門家にご確認ください。"
        )

        # ⑥ 分析開始ボタン
        submitted: bool = st.form_submit_button("分析開始", type="primary")

    if not submitted:
        return

    # バリデーション
    errors = validate_inputs(fiscal_year, level, agreed)
    if errors:
        for e in errors:
            st.error(e)
        return

    # APIキー未設定メッセージ
    if not _is_api_key_available():
        st.info(
            "ℹ️ ANTHROPIC_API_KEY が未設定のため、モックモードで動作します。"
            " 実際のLLM分析を行う場合は環境変数 ANTHROPIC_API_KEY を設定してください。"
        )

    # 処理進捗表示
    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        if pdf_file is None:
            # Demo モード: pipeline_mock() を使用
            st.info("📄 PDFが未アップロードのため、デモデータを使用します。")
            report_md = run_demo_pipeline(
                company_name=company_name,
                fiscal_year=fiscal_year,
                level=level,
                progress_bar=progress_bar,
                status_text=status_text,
            )
        else:
            # フルパイプラインモード: M1→M2→M3→M4→M5
            report_md = run_full_pipeline(
                pdf_bytes=pdf_file.read(),
                fiscal_year=fiscal_year,
                fiscal_month_end=3,   # Phase 1: 3月決算のみ対応
                level=level,
                company_name=company_name,
                progress_bar=progress_bar,
                status_text=status_text,
            )

        st.session_state.result_md = report_md
        st.session_state.step = "result"
        st.rerun()

    except FileNotFoundError as exc:
        st.error(f"ファイルが見つかりません: {exc}")
    except RuntimeError as exc:
        st.error(f"処理エラー（PyMuPDF等の依存ライブラリを確認してください）: {exc}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"処理中にエラーが発生しました: {exc}")
    finally:
        progress_bar.empty()
        status_text.empty()


# ─────────────────────────────────────────────────────────
# 画面: 結果表示
# ─────────────────────────────────────────────────────────


def render_result() -> None:
    """結果表示画面を描画する。"""
    st.title("✅ レポート生成完了")
    result_md: str = st.session_state.result_md or ""

    col_dl, col_back = st.columns([2, 1])
    with col_dl:
        # Markdownダウンロードボタン
        filename = f"disclosure_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        st.download_button(
            label="📥 Markdown をダウンロード",
            data=result_md,
            file_name=filename,
            mime="text/markdown",
        )
    with col_back:
        if st.button("🔄 別のファイルを分析"):
            st.session_state.step = "upload"
            st.session_state.result_md = None
            st.rerun()

    st.divider()
    # レポートをMarkdownとしてプレビュー表示
    st.markdown(result_md)


# ─────────────────────────────────────────────────────────
# メインルーティング（Streamlit app エントリポイント）
# ─────────────────────────────────────────────────────────


def main() -> None:
    """Streamlit アプリのメインエントリポイント。"""
    st.set_page_config(
        page_title="開示変更レポート生成",
        page_icon="📋",
        layout="wide",
    )

    # セッション状態の初期化
    if "result_md" not in st.session_state:
        st.session_state.result_md = None
    if "step" not in st.session_state:
        st.session_state.step = "upload"

    # 画面ルーティング
    step = st.session_state.step
    if step == "upload":
        render_upload()
    elif step == "result":
        render_result()
    else:
        # 不正な step 値 → リセット
        st.session_state.step = "upload"
        st.rerun()


# Streamlit は script 全体をモジュールとして実行する（`streamlit run app.py`）。
# `python3 -c "import app"` でのインポート時は Streamlit のセッションコンテキストが
# 存在しないため、main() を直接呼び出すと一部の st.* が例外を発生させる場合がある。
# ここでは _is_streamlit_running() ガードを用いて安全に処理する。
def _is_streamlit_running() -> bool:
    """Streamlit のアクティブセッション内で実行されているか確認する。"""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if _is_streamlit_running():
    main()
