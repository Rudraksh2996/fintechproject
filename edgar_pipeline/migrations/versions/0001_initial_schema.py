"""Initial insider schema, database invariants, role grants, and notifications.

Revision ID: 0001
This revision contains a frozen DDL snapshot; it never imports the current ORM schema.
"""

import os

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA_DDL: tuple[str, ...] = (
    (
        "CREATE TABLE companies (\n"
        "\tid BIGSERIAL NOT NULL, \n"
        "\tcik VARCHAR(10) NOT NULL, \n"
        "\tticker VARCHAR(32), \n"
        "\tname TEXT NOT NULL, \n"
        "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tCONSTRAINT pk_companies PRIMARY KEY (id), \n"
        "\tCONSTRAINT uq_companies_cik UNIQUE (cik)\n"
        ")"
    ),
    (
        "CREATE TABLE detection_configs (\n"
        "\tid BIGSERIAL NOT NULL, \n"
        "\tname TEXT NOT NULL, \n"
        "\tis_active BOOLEAN DEFAULT false NOT NULL, \n"
        "\twindow_days INTEGER DEFAULT '14' NOT NULL, \n"
        "\tmin_insiders INTEGER DEFAULT '3' NOT NULL, \n"
        "\tmin_insider_value_usd NUMERIC(24, 6) DEFAULT '25000' NOT NULL, \n"
        "\tmin_cluster_value_usd NUMERIC(24, 6) DEFAULT '100000' NOT NULL, \n"
        "\tinclude_ten_percent_owners BOOLEAN DEFAULT false NOT NULL, \n"
        "\texclude_10b5_1 BOOLEAN DEFAULT false NOT NULL, \n"
        "\tnew_position_pct NUMERIC(18, 8) DEFAULT '1' NOT NULL, \n"
        "\tcap_insiders INTEGER DEFAULT '8' NOT NULL, \n"
        "\tvalue_cap_multiple NUMERIC(18, 8) DEFAULT '100' NOT NULL, \n"
        "\tholdings_cap NUMERIC(18, 8) DEFAULT '0.5' NOT NULL, \n"
        "\tw_b NUMERIC(9, 8) DEFAULT '0.30' NOT NULL, \n"
        "\tw_c NUMERIC(9, 8) DEFAULT '0.25' NOT NULL, \n"
        "\tw_v NUMERIC(9, 8) DEFAULT '0.25' NOT NULL, \n"
        "\tw_h NUMERIC(9, 8) DEFAULT '0.20' NOT NULL, \n"
        "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tCONSTRAINT pk_detection_configs PRIMARY KEY (id), \n"
        "\tCONSTRAINT ck_detection_configs_window_and_buyers CHECK (window_days > "
        "0 AND min_insiders >= 2 AND cap_insiders >= min_insiders), \n"
        "\tCONSTRAINT ck_detection_configs_positive_thresholds CHECK (min_insider_"
        "value_usd > 0 AND min_cluster_value_usd > 0), \n"
        "\tCONSTRAINT ck_detection_configs_positive_caps CHECK (value_cap_multiple"
        " > 1 AND holdings_cap > 0 AND new_position_pct > 0), \n"
        "\tCONSTRAINT ck_detection_configs_weights CHECK (w_b >= 0 AND w_c >= 0 AN"
        "D w_v >= 0 AND w_h >= 0 AND w_b + w_c + w_v + w_h = 1)\n"
        ")"
    ),
    (
        "CREATE TABLE ingestion_runs (\n"
        "\tid BIGSERIAL NOT NULL, \n"
        "\tsource VARCHAR(16) NOT NULL, \n"
        "\tparameters JSONB NOT NULL, \n"
        "\tstatus VARCHAR(16) DEFAULT 'running' NOT NULL, \n"
        "\tfilings_seen INTEGER DEFAULT '0' NOT NULL, \n"
        "\ttransactions_inserted INTEGER DEFAULT '0' NOT NULL, \n"
        "\terrors INTEGER DEFAULT '0' NOT NULL, \n"
        "\terror_detail TEXT, \n"
        "\tstarted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tfinished_at TIMESTAMP WITH TIME ZONE, \n"
        "\tCONSTRAINT pk_ingestion_runs PRIMARY KEY (id), \n"
        "\tCONSTRAINT ck_ingestion_runs_status CHECK (status IN ('running', 'compl"
        "eted', 'failed'))\n"
        ")"
    ),
    (
        "CREATE TABLE insiders (\n"
        "\tid BIGSERIAL NOT NULL, \n"
        "\tcik VARCHAR(10) NOT NULL, \n"
        "\tname TEXT NOT NULL, \n"
        "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tCONSTRAINT pk_insiders PRIMARY KEY (id), \n"
        "\tCONSTRAINT uq_insiders_cik UNIQUE (cik)\n"
        ")"
    ),
    (
        "CREATE TABLE price_bars (\n"
        "\tticker VARCHAR(32) NOT NULL, \n"
        "\tdate DATE NOT NULL, \n"
        "\tclose NUMERIC(28, 8) NOT NULL, \n"
        "\tsource VARCHAR(32) NOT NULL, \n"
        "\tCONSTRAINT pk_price_bars PRIMARY KEY (ticker, date), \n"
        "\tCONSTRAINT ck_price_bars_positive_close CHECK (close > 0)\n"
        ")"
    ),
    (
        "CREATE TABLE cluster_alerts (\n"
        "\tid BIGSERIAL NOT NULL, \n"
        "\tcompany_id BIGINT NOT NULL, \n"
        "\tticker VARCHAR(32) NOT NULL, \n"
        "\twindow_start DATE NOT NULL, \n"
        "\twindow_end DATE NOT NULL, \n"
        "\tfirst_filing_date DATE NOT NULL, \n"
        "\talert_filing_date DATE NOT NULL, \n"
        "\tn_insiders INTEGER NOT NULL, \n"
        "\tn_csuite INTEGER NOT NULL, \n"
        "\ttotal_value_usd NUMERIC(28, 8) NOT NULL, \n"
        "\tavg_pct_holdings_increase NUMERIC(28, 8), \n"
        "\tconviction_score NUMERIC(5, 2) NOT NULL, \n"
        "\tscore_breakdown JSONB NOT NULL, \n"
        "\tconfig_id BIGINT NOT NULL, \n"
        "\tstatus VARCHAR(16) DEFAULT 'new' NOT NULL, \n"
        "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tCONSTRAINT pk_cluster_alerts PRIMARY KEY (id), \n"
        "\tCONSTRAINT uq_cluster_window_config UNIQUE (company_id, window_start, c"
        "onfig_id), \n"
        "\tCONSTRAINT ck_cluster_alerts_status CHECK (status IN ('new', 'acknowled"
        "ged', 'dismissed')), \n"
        "\tCONSTRAINT ck_cluster_alerts_score CHECK (conviction_score BETWEEN 0 AN"
        "D 100), \n"
        "\tCONSTRAINT ck_cluster_alerts_dates CHECK (window_end >= window_start AN"
        "D alert_filing_date >= first_filing_date), \n"
        "\tCONSTRAINT fk_cluster_alerts_company_id_companies FOREIGN KEY(company_i"
        "d) REFERENCES companies (id), \n"
        "\tCONSTRAINT fk_cluster_alerts_config_id_detection_configs FOREIGN KEY(co"
        "nfig_id) REFERENCES detection_configs (id)\n"
        ")"
    ),
    (
        "CREATE TABLE form4_filings (\n"
        "\taccession_number VARCHAR(32) NOT NULL, \n"
        "\tcompany_id BIGINT NOT NULL, \n"
        "\tfiling_date DATE NOT NULL, \n"
        "\tperiod_of_report DATE, \n"
        "\tform_type VARCHAR(3) NOT NULL, \n"
        "\tsupersedes_accession VARCHAR(32), \n"
        "\tsource VARCHAR(16) NOT NULL, \n"
        "\traw_xml_url TEXT NOT NULL, \n"
        "\traw_xml TEXT NOT NULL, \n"
        "\tsha256 VARCHAR(64) NOT NULL, \n"
        "\tingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tCONSTRAINT pk_form4_filings PRIMARY KEY (accession_number), \n"
        "\tCONSTRAINT ck_form4_filings_form_type CHECK (form_type IN ('4', '4/A'))"
        ", \n"
        "\tCONSTRAINT ck_form4_filings_source CHECK (source IN ('synthetic', 'sec_"
        "edgar')), \n"
        "\tCONSTRAINT fk_form4_filings_company_id_companies FOREIGN KEY(company_id"
        ") REFERENCES companies (id), \n"
        "\tCONSTRAINT fk_form4_filings_supersedes_accession_form4_filings FOREIGN "
        "KEY(supersedes_accession) REFERENCES form4_filings (accession_number)\n"
        ")"
    ),
    (
        "CREATE TABLE parse_errors (\n"
        "\tid BIGSERIAL NOT NULL, \n"
        "\taccession_number VARCHAR(32), \n"
        "\tingestion_run_id BIGINT, \n"
        "\traw_xml_url TEXT NOT NULL, \n"
        "\traw_xml TEXT NOT NULL, \n"
        "\terror_type TEXT NOT NULL, \n"
        "\terror_detail TEXT NOT NULL, \n"
        "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tCONSTRAINT pk_parse_errors PRIMARY KEY (id), \n"
        "\tCONSTRAINT fk_parse_errors_ingestion_run_id_ingestion_runs FOREIGN KEY("
        "ingestion_run_id) REFERENCES ingestion_runs (id)\n"
        ")"
    ),
    (
        "CREATE TABLE form4_transactions (\n"
        "\tid BIGSERIAL NOT NULL, \n"
        "\taccession_number VARCHAR(32) NOT NULL, \n"
        "\tline_number INTEGER NOT NULL, \n"
        "\tcompany_id BIGINT NOT NULL, \n"
        "\tinsider_id BIGINT NOT NULL, \n"
        "\tticker VARCHAR(32), \n"
        "\ttransaction_date DATE NOT NULL, \n"
        "\tfiling_date DATE NOT NULL, \n"
        "\ttransaction_code VARCHAR(1) NOT NULL, \n"
        "\tacquired_disposed VARCHAR(1) NOT NULL, \n"
        "\tshares NUMERIC(28, 8) NOT NULL, \n"
        "\tprice NUMERIC(28, 8), \n"
        "\tvalue_usd NUMERIC(28, 8), \n"
        "\tshares_owned_after NUMERIC(28, 8), \n"
        "\tpct_holdings_increase NUMERIC(28, 8), \n"
        "\tis_director BOOLEAN DEFAULT false NOT NULL, \n"
        "\tis_officer BOOLEAN DEFAULT false NOT NULL, \n"
        "\tis_ten_percent_owner BOOLEAN DEFAULT false NOT NULL, \n"
        "\tis_other BOOLEAN DEFAULT false NOT NULL, \n"
        "\tofficer_title TEXT, \n"
        "\tis_csuite BOOLEAN DEFAULT false NOT NULL, \n"
        "\tis_10b5_1 BOOLEAN DEFAULT false NOT NULL, \n"
        "\tis_amendment BOOLEAN DEFAULT false NOT NULL, \n"
        "\tsuperseded BOOLEAN DEFAULT false NOT NULL, \n"
        "\tis_new_position BOOLEAN DEFAULT false NOT NULL, \n"
        "\tmissing_price BOOLEAN DEFAULT false NOT NULL, \n"
        "\tdirect_or_indirect VARCHAR(1), \n"
        "\tfootnote_refs JSONB DEFAULT '[]'::jsonb NOT NULL, \n"
        "\traw_xml_url TEXT NOT NULL, \n"
        "\tingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n"
        "\tCONSTRAINT pk_form4_transactions PRIMARY KEY (id), \n"
        "\tCONSTRAINT uq_form4_accession_line UNIQUE (accession_number, line_numbe"
        "r), \n"
        "\tCONSTRAINT ck_form4_transactions_positive_line_shares CHECK (line_numbe"
        "r > 0 AND shares >= 0), \n"
        "\tCONSTRAINT ck_form4_transactions_acquired_disposed CHECK (acquired_disp"
        "osed IN ('A', 'D')), \n"
        "\tCONSTRAINT fk_form4_transactions_accession_number_form4_filings FOREIGN"
        " KEY(accession_number) REFERENCES form4_filings (accession_number), \n"
        "\tCONSTRAINT fk_form4_transactions_company_id_companies FOREIGN KEY(compa"
        "ny_id) REFERENCES companies (id), \n"
        "\tCONSTRAINT fk_form4_transactions_insider_id_insiders FOREIGN KEY(inside"
        "r_id) REFERENCES insiders (id)\n"
        ")"
    ),
    (
        "CREATE TABLE cluster_alert_members (\n"
        "\talert_id BIGINT NOT NULL, \n"
        "\ttransaction_id BIGINT NOT NULL, \n"
        "\tCONSTRAINT pk_cluster_alert_members PRIMARY KEY (alert_id, transaction_"
        "id), \n"
        "\tCONSTRAINT fk_cluster_alert_members_alert_id_cluster_alerts FOREIGN KEY"
        "(alert_id) REFERENCES cluster_alerts (id) ON DELETE CASCADE, \n"
        "\tCONSTRAINT fk_cluster_alert_members_transaction_id_form4_transactions F"
        "OREIGN KEY(transaction_id) REFERENCES form4_transactions (id)\n"
        ")"
    ),
    (
        "CREATE UNIQUE INDEX uq_detection_configs_active ON detection_configs (is"
        "_active) WHERE is_active"
    ),
    ("CREATE INDEX ix_cluster_alerts_filing_date ON cluster_alerts (alert_filing_date)"),
    ("CREATE INDEX ix_form4_company_date ON form4_transactions (company_id, transaction_date)"),
    ("CREATE INDEX ix_form4_filing_date ON form4_transactions (filing_date)"),
    ("CREATE INDEX ix_form4_ticker_date ON form4_transactions (ticker, transaction_date)"),
)
TABLES: tuple[str, ...] = (
    "companies",
    "detection_configs",
    "ingestion_runs",
    "insiders",
    "price_bars",
    "cluster_alerts",
    "form4_filings",
    "parse_errors",
    "form4_transactions",
    "cluster_alert_members",
)


def upgrade() -> None:
    for statement in SCHEMA_DDL:
        op.execute(sa.text(statement))
    op.execute(
        sa.text("""
        CREATE FUNCTION notify_cluster_alert() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_notify('cluster_alerts', NEW.id::text);
            RETURN NEW;
        END;
        $$
    """)
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER cluster_alert_inserted AFTER INSERT ON cluster_alerts
        FOR EACH ROW EXECUTE FUNCTION notify_cluster_alert()
    """)
    )
    op.execute(
        sa.text("""
        CREATE FUNCTION enforce_one_active_config() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (SELECT count(*) FROM detection_configs WHERE is_active) <> 1 THEN
                RAISE EXCEPTION 'Exactly one detection config must be active'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
    """)
    )
    op.execute(
        sa.text("""
        CREATE CONSTRAINT TRIGGER detection_configs_one_active
        AFTER INSERT OR UPDATE OR DELETE ON detection_configs
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION enforce_one_active_config()
    """)
    )
    op.execute(
        sa.text("""
        CREATE FUNCTION touch_company_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
    """)
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER companies_updated BEFORE UPDATE ON companies
        FOR EACH ROW EXECUTE FUNCTION touch_company_updated_at()
    """)
    )
    op.execute(sa.text("INSERT INTO detection_configs (name, is_active) VALUES ('Default', true)"))
    quote = op.get_context().dialect.identifier_preparer.quote
    app_role = quote(os.environ.get("POSTGRES_APP_USER", "fintech_app"))
    table_list = ", ".join(quote(name) for name in TABLES)
    op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table_list} TO {app_role}"))
    op.execute(sa.text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app_role}"))
    op.execute(sa.text(f"GRANT SELECT ON {table_list} TO workbench_ro"))
    op.execute(sa.text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM workbench_ro"))
    op.execute(
        sa.text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO workbench_ro")
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER cluster_alert_inserted ON cluster_alerts"))
    op.execute(sa.text("DROP FUNCTION notify_cluster_alert()"))
    op.execute(sa.text("DROP TRIGGER detection_configs_one_active ON detection_configs"))
    op.execute(sa.text("DROP FUNCTION enforce_one_active_config()"))
    op.execute(sa.text("DROP TRIGGER companies_updated ON companies"))
    op.execute(sa.text("DROP FUNCTION touch_company_updated_at()"))
    op.execute(
        sa.text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM workbench_ro"
        )
    )
    for table in reversed(TABLES):
        op.drop_table(table)
