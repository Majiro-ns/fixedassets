-- yuka-ai SQLiteスキーマ定義
-- 資材調達AIエージェント: 品番管理・価格履歴・サプライヤー・発注・交渉履歴
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- =========================================================================
-- 1. サプライヤー（取引先）マスタ
-- =========================================================================
CREATE TABLE IF NOT EXISTS suppliers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    code            TEXT UNIQUE,
    postal_code     TEXT,
    address         TEXT,
    department      TEXT,
    contact_person  TEXT,
    tel             TEXT,
    fax             TEXT,
    email           TEXT,
    payment_terms   TEXT DEFAULT '月末締め翌月末払い',
    notes           TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- =========================================================================
-- 2. 品番マスタ
-- =========================================================================
CREATE TABLE IF NOT EXISTS parts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    part_number     TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL,
    category        TEXT,                         -- ボルト/工具/安全用品等
    unit            TEXT DEFAULT '個',
    min_order_qty   INTEGER DEFAULT 1,
    lead_time_days  INTEGER,
    preferred_supplier_id INTEGER REFERENCES suppliers(id),
    ec_site         TEXT DEFAULT 'monotaro',      -- monotaro/askul/misumi
    ec_url          TEXT,
    notes           TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- =========================================================================
-- 3. 価格履歴（品番×サプライヤー×日付）
-- =========================================================================
CREATE TABLE IF NOT EXISTS price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id         INTEGER NOT NULL REFERENCES parts(id),
    supplier_id     INTEGER REFERENCES suppliers(id),
    price           REAL NOT NULL,
    currency        TEXT DEFAULT 'JPY',
    price_type      TEXT DEFAULT 'list',          -- list/quoted/negotiated/contract
    source          TEXT,                         -- monotaro/手入力/見積書等
    fetched_at      TEXT DEFAULT (datetime('now', 'localtime')),
    valid_from      TEXT,
    valid_until     TEXT,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_price_part_date
    ON price_history(part_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_supplier
    ON price_history(supplier_id, fetched_at DESC);

-- =========================================================================
-- 4. 価格アラート設定
-- =========================================================================
-- アラート閾値設計:
--   ±3%未満  → OK（正常変動）
--   ±3〜5%  → INFO（記録のみ）
--   ±5〜10% → WARNING（担当者に通知）
--   ±10%超  → CRITICAL（即座に交渉メール提案）
CREATE TABLE IF NOT EXISTS price_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id         INTEGER NOT NULL REFERENCES parts(id),
    alert_type      TEXT NOT NULL,                -- increase/decrease/threshold
    threshold_pct   REAL DEFAULT 5.0,             -- 変動率閾値%
    threshold_abs   REAL,                         -- 絶対額閾値
    is_active       INTEGER DEFAULT 1,
    last_triggered  TEXT,
    created_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- =========================================================================
-- 5. 発注書ヘッダー
-- =========================================================================
CREATE TABLE IF NOT EXISTS purchase_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number       TEXT NOT NULL UNIQUE,
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id),
    status          TEXT DEFAULT 'draft',         -- draft/sent/confirmed/delivered/cancelled
    issue_date      TEXT,
    delivery_date   TEXT,
    delivery_location TEXT,
    payment_terms   TEXT,
    total_amount    REAL DEFAULT 0,
    tax_amount      REAL DEFAULT 0,
    grand_total     REAL DEFAULT 0,
    notes           TEXT,
    excel_path      TEXT,
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- =========================================================================
-- 6. 発注明細
-- =========================================================================
CREATE TABLE IF NOT EXISTS purchase_order_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id           INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_no         INTEGER NOT NULL,
    part_id         INTEGER REFERENCES parts(id),
    part_number     TEXT NOT NULL,
    description     TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    unit            TEXT DEFAULT '個',
    unit_price      REAL NOT NULL,
    subtotal        REAL NOT NULL,
    note            TEXT
);

-- =========================================================================
-- 7. 交渉履歴
-- =========================================================================
CREATE TABLE IF NOT EXISTS negotiations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id),
    part_id         INTEGER REFERENCES parts(id),
    negotiation_type TEXT NOT NULL,               -- volume_discount/long_term/competitor/price_change
    status          TEXT DEFAULT 'draft',         -- draft/sent/replied/agreed/rejected
    original_price  REAL,
    target_price    REAL,
    agreed_price    REAL,
    email_subject   TEXT,
    email_body      TEXT,
    response_body   TEXT,
    sent_at         TEXT,
    responded_at    TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- =========================================================================
-- 8. メール送信履歴
-- =========================================================================
CREATE TABLE IF NOT EXISTS email_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    negotiation_id  INTEGER REFERENCES negotiations(id),
    direction       TEXT NOT NULL,                -- sent/received
    from_addr       TEXT,
    to_addr         TEXT,
    subject         TEXT,
    body            TEXT,
    sent_at         TEXT DEFAULT (datetime('now', 'localtime')),
    message_id      TEXT
);

-- =========================================================================
-- 9. 納期管理（F-13）
-- =========================================================================
CREATE TABLE IF NOT EXISTS delivery_tracking (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    part_number             TEXT NOT NULL,
    supplier_name           TEXT NOT NULL,
    order_date              TEXT NOT NULL,
    expected_delivery_date  TEXT NOT NULL,
    quantity                INTEGER DEFAULT 1,
    unit_price              REAL,
    status                  TEXT DEFAULT 'pending',  -- pending/received/overdue
    notes                   TEXT,
    created_at              TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at              TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_delivery_part_date
    ON delivery_tracking(part_number, expected_delivery_date);
CREATE INDEX IF NOT EXISTS idx_delivery_status
    ON delivery_tracking(status, expected_delivery_date);

-- =========================================================================
-- ビュー: 品番ごとの最新価格 + 前回比較
-- =========================================================================
CREATE VIEW IF NOT EXISTS v_latest_prices AS
SELECT
    p.id AS part_id,
    p.part_number,
    p.description,
    p.category,
    ph.price AS latest_price,
    ph.fetched_at AS price_date,
    ph.source,
    prev.price AS prev_price,
    prev.fetched_at AS prev_date,
    CASE
        WHEN prev.price IS NOT NULL AND prev.price > 0
        THEN ROUND((ph.price - prev.price) / prev.price * 100, 1)
        ELSE NULL
    END AS change_pct
FROM parts p
JOIN price_history ph ON ph.id = (
    SELECT id FROM price_history WHERE part_id = p.id ORDER BY fetched_at DESC, id DESC LIMIT 1
)
LEFT JOIN price_history prev ON prev.id = (
    SELECT id FROM price_history WHERE part_id = p.id ORDER BY fetched_at DESC, id DESC LIMIT 1 OFFSET 1
)
WHERE p.is_active = 1;

-- =========================================================================
-- ビュー: アラート対象品番
-- =========================================================================
CREATE VIEW IF NOT EXISTS v_price_alerts AS
SELECT
    lp.part_number, lp.description,
    lp.latest_price, lp.prev_price, lp.change_pct,
    pa.alert_type, pa.threshold_pct,
    CASE
        WHEN ABS(lp.change_pct) >= 10 THEN 'CRITICAL'
        WHEN ABS(lp.change_pct) >= 5  THEN 'WARNING'
        WHEN ABS(lp.change_pct) >= 3  THEN 'INFO'
        ELSE 'OK'
    END AS alert_level
FROM v_latest_prices lp
JOIN price_alerts pa ON pa.part_id = lp.part_id AND pa.is_active = 1
WHERE lp.change_pct IS NOT NULL
  AND ABS(lp.change_pct) >= COALESCE(pa.threshold_pct, 3.0);

-- =========================================================================
-- 10. 在庫管理（T007: 発注自動化ワークフロー）
-- =========================================================================
CREATE TABLE IF NOT EXISTS inventory (
    part_id         INTEGER PRIMARY KEY REFERENCES parts(id) ON DELETE CASCADE,
    current_stock   INTEGER NOT NULL DEFAULT 0,
    reorder_point   INTEGER NOT NULL DEFAULT 10,
    updated_at      TEXT DEFAULT (datetime('now', 'localtime'))
);
