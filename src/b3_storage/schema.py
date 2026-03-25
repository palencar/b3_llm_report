REQUIRED_TABLES = [
    "companies",
    "fundamentals",
    "prices",
    "ratios",
    "raw_files",
    "cvm_companies",
    "cvm_statements",
]

# DDL de referencia (nao executado automaticamente).
SCHEMA_SQL = """
-- companies
CREATE TABLE IF NOT EXISTS companies (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    industry TEXT,
    last_update TIMESTAMP,
    source TEXT,
    updated_at TIMESTAMP
);

-- fundamentals
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT,
    period DATE,
    statement_type TEXT,
    key TEXT,
    value DOUBLE,
    currency TEXT,
    source TEXT,
    fetched_at TIMESTAMP,
    PRIMARY KEY (ticker, period, statement_type, key)
);

-- prices
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT,
    ts TIMESTAMP,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    source TEXT,
    PRIMARY KEY (ticker, ts)
);

-- ratios
CREATE TABLE IF NOT EXISTS ratios (
    ticker TEXT,
    period DATE,
    ratio_name TEXT,
    value DOUBLE,
    computed_at TIMESTAMP,
    PRIMARY KEY (ticker, period, ratio_name)
);

-- raw_files
CREATE TABLE IF NOT EXISTS raw_files (
    source TEXT,
    path TEXT,
    fetched_at TIMESTAMP,
    checksum TEXT,
    size_bytes BIGINT,
    PRIMARY KEY (source, path)
);

-- cvm_companies
CREATE TABLE IF NOT EXISTS cvm_companies (
    cnpj        TEXT PRIMARY KEY,
    name        TEXT,
    cd_cvm      TEXT,
    fetched_at  TIMESTAMP
);

-- cvm_statements
CREATE TABLE IF NOT EXISTS cvm_statements (
    cnpj         TEXT,
    period       DATE,
    report_type  TEXT,
    account_code TEXT,
    account_name TEXT,
    value        DOUBLE,
    currency     TEXT,
    source       TEXT,
    fetched_at   TIMESTAMP,
    PRIMARY KEY (cnpj, period, report_type, account_code, source)
);
""".strip()
