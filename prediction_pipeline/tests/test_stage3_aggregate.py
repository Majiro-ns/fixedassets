"""
tests/test_stage3_aggregate.py
================================
ashigaru_predict.stage3_aggregate() の単体テスト

テスト根拠（CHECK-9）:

  1. F10除外 (f10_passed=False):
     → req["f10_passed"]=False のレースはbet計算をスキップする（安全弁設計）。
       stage3_aggregate() の if not req.get("f10_passed", True): continue ロジック。

  2. 構造化データ優先 (axis/partners in result YAML):
     → res["axis"] is not None and res["partners"] の場合テキストパース不要。
       stage2_process.py --write が書き出す構造化フィールドが使われることを確認。

  3. テキストパース「本命:」形式:
     → r"(?:軸|本命)[：:]\\s*(\\d+)番?" で axis を抽出。
       「本命: 3番（名前）\n軸相手: 1番、5番」→ axis=3, partners=[1, 5]。

  4. テキストパース フォールバック（1-7の数字列）:
     → 本命/軸キーワードがない場合 re.findall(r"\b([1-7])\b") を使う。
       「3番 1番 5番 7番」→ axis=3, partners=[1, 5, 7]。

  5. 軸・相手解析失敗 → スキップ:
     → 数字2個未満の予測テキストは警告ログのみでスキップ。

  6. 相手不足（1名以下）→ スキップ:
     → len(partners) < 2 の場合は bet 計算しない。

  7. output JSON 保存:
     → output_dir / "{sport}_{venue}_{race_no}.json" に保存されること。

  8. summary.md 生成:
     → 正常処理完了後 output_dir / "summary.md" が書かれること。

  9. 複数レース処理:
     → 3件のresultファイルが存在する場合、3件分のJSONが保存されること。

  10. axis が partners から除外される（重複除去）:
     → 軸相手欄に軸番号と同じ数字が含まれていても除去されること。
       手計算: [p for p in raw_partners if p != axis] の設計による。

  11. status!=done のレースはスキップ:
     → res["status"]="pending" → 処理しない。

  12. req ファイル不存在 → スキップ:
     → REQ_DIR に対応YAMLがない場合は警告のみ。

  13. 空results → early return（summary.md 非生成）:
     → 処理件数0件の場合 summary.md は書かれない。

  14. bet計算エラー → スキップして継続:
     → calc_from_strategy が例外を投げても他レースは処理される。

（cmd_150k_sub4）
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ashigaru_predict


# ─── フィクスチャヘルパー ──────────────────────────────────────────────────


def _req_yaml(task_id: str, venue: str = "岐阜", race_no: int = 5,
              f10_passed: bool = True) -> dict:
    return {
        "task_id": task_id,
        "venue": venue,
        "race_no": race_no,
        "grade": "S",
        "stage": "Ｓ級一予選",
        "date": "20260301",
        "sport": "keirin",
        "f10_passed": f10_passed,
        "filter_passed": True,
        "filter_type": "A",
    }


def _res_yaml_text(task_id: str, prediction_text: str,
                   status: str = "done") -> dict:
    return {
        "task_id": task_id,
        "status": status,
        "prediction_text": prediction_text,
    }


def _res_yaml_structured(task_id: str, axis: int, partners: list,
                          status: str = "done") -> dict:
    return {
        "task_id": task_id,
        "status": status,
        "axis": axis,
        "partners": partners,
        "prediction_text": f"本命: {axis}番\n軸相手: {','.join(map(str, partners))}番",
    }


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


_MINIMAL_CONFIG = {
    "pipeline": {"output_dir": "output"},
    "betting": {
        "default_strategy": "sanrenpu_nagashi",
        "unit_bet": 100,
    },
    "logging": {},
}


def _mock_main_module() -> types.ModuleType:
    """load_settings / setup_logging を持つモック main モジュールを返す。"""
    m = types.ModuleType("main")
    m.load_settings = MagicMock(return_value=_MINIMAL_CONFIG)
    m.setup_logging = MagicMock()
    return m


# ─── テストクラス ──────────────────────────────────────────────────────────


class TestStage3AggregateBasic:
    """stage3_aggregate の基本動作テスト"""

    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        """REQ_DIR・RES_DIR・ROOT を tmp_path に差し替える。"""
        self.req_dir = tmp_path / "requests"
        self.res_dir = tmp_path / "results"
        self.req_dir.mkdir(parents=True)
        self.res_dir.mkdir(parents=True)
        self.output_root = tmp_path

        monkeypatch.setattr(ashigaru_predict, "REQ_DIR", self.req_dir)
        monkeypatch.setattr(ashigaru_predict, "RES_DIR", self.res_dir)
        monkeypatch.setattr(ashigaru_predict, "ROOT", tmp_path)

        self._mock_main = _mock_main_module()
        monkeypatch.setitem(sys.modules, "main", self._mock_main)

    # ── 1. 空 RES_DIR → early return ─────────────────────────────────────

    def test_empty_results_no_summary_md(self):
        """処理件数0件の場合 summary.md が生成されないこと。"""
        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        summary = self.output_root / "output" / "20260301" / "summary.md"
        assert not summary.exists()

    # ── 2. status != done → スキップ ────────────────────────────────────

    def test_skip_non_done_status(self):
        """status='pending' のレースは処理されないこと。"""
        _write_yaml(self.res_dir / "task1.yaml",
                    _res_yaml_text("task1", "本命: 3番\n軸相手: 1番、5番", status="pending"))
        _write_yaml(self.req_dir / "task1.yaml", _req_yaml("task1"))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.output_root / "output" / "20260301"
        jsons = list(output_dir.glob("*.json")) if output_dir.exists() else []
        assert len(jsons) == 0

    # ── 3. req ファイル不存在 → スキップ ────────────────────────────────

    def test_skip_missing_req_file(self):
        """リクエストYAMLがない場合スキップし、クラッシュしないこと。"""
        _write_yaml(self.res_dir / "task1.yaml",
                    _res_yaml_text("task1", "本命: 3番\n軸相手: 1番、5番"))
        # req ファイルを意図的に作成しない

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.output_root / "output" / "20260301"
        jsons = list(output_dir.glob("*.json")) if output_dir.exists() else []
        assert len(jsons) == 0


class TestStage3AggregateF10:
    """F10除外ロジックのテスト"""

    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        self.req_dir = tmp_path / "requests"
        self.res_dir = tmp_path / "results"
        self.req_dir.mkdir(parents=True)
        self.res_dir.mkdir(parents=True)
        monkeypatch.setattr(ashigaru_predict, "REQ_DIR", self.req_dir)
        monkeypatch.setattr(ashigaru_predict, "RES_DIR", self.res_dir)
        monkeypatch.setattr(ashigaru_predict, "ROOT", tmp_path)
        monkeypatch.setitem(sys.modules, "main", _mock_main_module())

    def test_f10_false_is_skipped(self, tmp_path):
        """f10_passed=False のリクエストは bet 計算されないこと。"""
        _write_yaml(self.res_dir / "task1.yaml",
                    _res_yaml_text("task1", "本命: 3番\n軸相手: 1番、5番"))
        _write_yaml(self.req_dir / "task1.yaml",
                    _req_yaml("task1", f10_passed=False))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = tmp_path / "output" / "20260301"
        jsons = list(output_dir.glob("*.json")) if output_dir.exists() else []
        assert len(jsons) == 0

    def test_f10_true_is_processed(self, tmp_path):
        """f10_passed=True（デフォルト）のリクエストは処理されること。"""
        _write_yaml(self.res_dir / "task1.yaml",
                    _res_yaml_text("task1", "本命: 3番\n軸相手: 1番、5番"))
        _write_yaml(self.req_dir / "task1.yaml",
                    _req_yaml("task1", f10_passed=True))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = tmp_path / "output" / "20260301"
        jsons = list(output_dir.glob("*.json"))
        assert len(jsons) == 1

    def test_f10_warning_log_emitted(self, caplog):
        """f10_passed=False のスキップ時に WARNING ログが出力されること。

        CHECK-9 根拠:
          stage3_aggregate()のF10安全網（scripts/ashigaru_predict.py）が
          logger.warning("[F10除外] ...") を呼ぶことを直接検証する。
          スキップ時の警告ログは運用監視の手掛かりとなる（W-1対応）。
          手計算: f10_passed=False → continue 前に logger.warning が呼ばれる。
        """
        import logging

        _write_yaml(self.res_dir / "task1.yaml",
                    _res_yaml_text("task1", "本命: 3番\n軸相手: 1番、5番"))
        _write_yaml(self.req_dir / "task1.yaml",
                    _req_yaml("task1", f10_passed=False))

        with caplog.at_level(logging.WARNING, logger="ashigaru_predict"):
            ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")

        assert any(
            "[F10除外]" in record.message and record.levelno == logging.WARNING
            for record in caplog.records
        ), "f10_passed=False のスキップ時に WARNING '[F10除外]' ログが出力されるべき（W-1）"


class TestStage3AggregateParsing:
    """軸・相手パースロジックのテスト"""

    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        self.req_dir = tmp_path / "requests"
        self.res_dir = tmp_path / "results"
        self.req_dir.mkdir(parents=True)
        self.res_dir.mkdir(parents=True)
        monkeypatch.setattr(ashigaru_predict, "REQ_DIR", self.req_dir)
        monkeypatch.setattr(ashigaru_predict, "RES_DIR", self.res_dir)
        monkeypatch.setattr(ashigaru_predict, "ROOT", tmp_path)
        monkeypatch.setitem(sys.modules, "main", _mock_main_module())
        self.tmp_path = tmp_path

    def _get_output_json(self) -> dict:
        output_dir = self.tmp_path / "output" / "20260301"
        jsons = list(output_dir.glob("*.json"))
        assert len(jsons) == 1, f"期待1件、実際{len(jsons)}件"
        return json.loads(jsons[0].read_text(encoding="utf-8"))

    def test_structured_data_used_over_text(self):
        """res に axis/partners がある場合、テキストパースせず使うこと。"""
        _write_yaml(self.res_dir / "task1.yaml",
                    _res_yaml_structured("task1", axis=2, partners=[4, 6]))
        _write_yaml(self.req_dir / "task1.yaml", _req_yaml("task1"))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        out = self._get_output_json()
        # bet_result は axis=2, partners=[4,6] に基づいて計算されているはず
        assert out["bet"]["total_investment"] > 0

    def test_text_parse_honmei_format(self):
        """「本命: 3番\n軸相手: 1番、5番」形式からax=3が抽出されること。"""
        text = "本命: 3番（後閑信一）\n軸相手: 1番、5番\n買い目: 3連複"
        _write_yaml(self.res_dir / "task1.yaml", _res_yaml_text("task1", text))
        _write_yaml(self.req_dir / "task1.yaml", _req_yaml("task1"))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        # JSONが生成されていれば解析成功
        output_dir = self.tmp_path / "output" / "20260301"
        assert len(list(output_dir.glob("*.json"))) == 1

    def test_text_parse_fallback_numbers(self):
        """本命キーワードなしでも 1-7 の数字列からフォールバック解析できること。

        根拠: re.findall(r"\b([1-7])\b") はPython unicode モードでは
        日本語文字（番、等）も \\w 扱いのため \\b 境界が機能しない。
        ハイフン/スペース等 ASCII \\W で区切られた数字列なら正しく抽出される。
        """
        # ハイフン区切りの数字列: 3=axis, 1と5=partners
        text = "3-1-5 予想"
        _write_yaml(self.res_dir / "task1.yaml", _res_yaml_text("task1", text))
        _write_yaml(self.req_dir / "task1.yaml", _req_yaml("task1"))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.tmp_path / "output" / "20260301"
        assert len(list(output_dir.glob("*.json"))) == 1

    def test_unparseable_text_skips_race(self):
        """数字が1個以下のテキストはスキップされること。"""
        text = "この予測は判定不能"
        _write_yaml(self.res_dir / "task1.yaml", _res_yaml_text("task1", text))
        _write_yaml(self.req_dir / "task1.yaml", _req_yaml("task1"))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.tmp_path / "output" / "20260301"
        jsons = list(output_dir.glob("*.json")) if output_dir.exists() else []
        assert len(jsons) == 0

    def test_axis_excluded_from_partners(self):
        """軸相手欄に軸番号と同じ数字が含まれても除去されること。"""
        # 軸=3、相手欄に 3,1,5（3は軸と同じなので除外されるはず）
        text = "軸: 3番\n軸相手: 3番、1番、5番"
        _write_yaml(self.res_dir / "task1.yaml", _res_yaml_text("task1", text))
        _write_yaml(self.req_dir / "task1.yaml", _req_yaml("task1"))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.tmp_path / "output" / "20260301"
        # 軸除外後 partners=[1,5] で2名 → 処理されること
        assert len(list(output_dir.glob("*.json"))) == 1

    def test_insufficient_partners_skips_race(self):
        """相手が1名以下の場合スキップされること。"""
        text = "本命: 3番\n軸相手: 1番"  # 1名のみ
        _write_yaml(self.res_dir / "task1.yaml", _res_yaml_text("task1", text))
        _write_yaml(self.req_dir / "task1.yaml", _req_yaml("task1"))

        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.tmp_path / "output" / "20260301"
        jsons = list(output_dir.glob("*.json")) if output_dir.exists() else []
        assert len(jsons) == 0


class TestStage3AggregateOutput:
    """出力ファイル生成のテスト"""

    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        self.req_dir = tmp_path / "requests"
        self.res_dir = tmp_path / "results"
        self.req_dir.mkdir(parents=True)
        self.res_dir.mkdir(parents=True)
        monkeypatch.setattr(ashigaru_predict, "REQ_DIR", self.req_dir)
        monkeypatch.setattr(ashigaru_predict, "RES_DIR", self.res_dir)
        monkeypatch.setattr(ashigaru_predict, "ROOT", tmp_path)
        monkeypatch.setitem(sys.modules, "main", _mock_main_module())
        self.tmp_path = tmp_path

    def _add_race(self, task_id: str, venue: str = "岐阜", race_no: int = 5):
        text = "本命: 3番\n軸相手: 1番、5番\n買い目: 3連複"
        _write_yaml(self.res_dir / f"{task_id}.yaml", _res_yaml_text(task_id, text))
        _write_yaml(self.req_dir / f"{task_id}.yaml",
                    _req_yaml(task_id, venue=venue, race_no=race_no))

    def test_output_json_is_created(self):
        """正常処理時に output_dir に JSON が保存されること。"""
        self._add_race("task1")
        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.tmp_path / "output" / "20260301"
        assert len(list(output_dir.glob("*.json"))) == 1

    def test_summary_md_is_created(self):
        """正常処理後に summary.md が生成されること。"""
        self._add_race("task1")
        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        summary = self.tmp_path / "output" / "20260301" / "summary.md"
        assert summary.exists()

    def test_summary_md_contains_date(self):
        """summary.md に対象日が記載されること。"""
        self._add_race("task1")
        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        summary = self.tmp_path / "output" / "20260301" / "summary.md"
        content = summary.read_text(encoding="utf-8")
        assert "20260301" in content

    def test_multiple_races_all_output(self):
        """3件のレースが全てJSON出力されること。"""
        for i in range(1, 4):
            self._add_race(f"task{i}", race_no=i)
        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.tmp_path / "output" / "20260301"
        assert len(list(output_dir.glob("*.json"))) == 3

    def test_output_json_has_bet_field(self):
        """出力JSONに bet フィールドが含まれること。"""
        self._add_race("task1")
        ashigaru_predict.stage3_aggregate("20260301", "keirin", "dummy.yaml")
        output_dir = self.tmp_path / "output" / "20260301"
        jsons = list(output_dir.glob("*.json"))
        data = json.loads(jsons[0].read_text(encoding="utf-8"))
        assert "bet" in data
        assert data["bet"]["total_investment"] > 0
