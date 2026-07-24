-- SIRS PostgreSQL 初始化 DDL
-- 由 Python 或 Java 启动时执行

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email         VARCHAR(100),
    status        SMALLINT     DEFAULT 1,
    created_at    TIMESTAMP    DEFAULT NOW(),
    updated_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stocks (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(10)  NOT NULL UNIQUE,
    name        VARCHAR(50)  NOT NULL,
    exchange    VARCHAR(10),
    market      VARCHAR(20),
    industry    VARCHAR(50),
    listed_date DATE,
    is_active   BOOLEAN      DEFAULT TRUE,
    created_at  TIMESTAMP    DEFAULT NOW(),
    updated_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS groups (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users(id),
    name        VARCHAR(50)  NOT NULL,
    description VARCHAR(200),
    sort_order  INT          DEFAULT 0,
    created_at  TIMESTAMP    DEFAULT NOW(),
    updated_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS group_stocks (
    id          BIGSERIAL PRIMARY KEY,
    group_id    BIGINT       NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    stock_code  VARCHAR(10)  NOT NULL REFERENCES stocks(code),
    added_at    TIMESTAMP    DEFAULT NOW(),
    UNIQUE (group_id, stock_code)
);

-- ═══════════════════════════════════════════════
-- 通知系统
-- ═══════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS notifications (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users(id),
    stock_code  VARCHAR(10)  NOT NULL,
    stock_name  VARCHAR(50)  NOT NULL,
    type        VARCHAR(30)  NOT NULL,
    message     VARCHAR(500) NOT NULL,
    detail      JSONB,
    is_read     BOOLEAN      DEFAULT FALSE,
    created_at  TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_type
    ON notifications(type);

CREATE TABLE IF NOT EXISTS stock_signal_state (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              BIGINT       NOT NULL REFERENCES users(id),
    stock_code           VARCHAR(10)  NOT NULL,
    signal_state         VARCHAR(30)  NOT NULL DEFAULT 'NONE',
    golden_cross_date    DATE,
    white_buy_notified   BOOLEAN      DEFAULT FALSE,
    yellow_buy_notified  BOOLEAN      DEFAULT FALSE,
    updated_at           TIMESTAMP    DEFAULT NOW(),
    UNIQUE (user_id, stock_code)
);

-- 兜底去重：同一用户同一天同一股票同一类型只允许一条通知
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_unique_daily
    ON notifications(user_id, stock_code, type, (created_at::date));
