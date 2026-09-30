-- Cópia read-only de script-datamart.sql (delta-database, branch
-- feat/data-mart-industrial-bi), sem dw.vw_audit_history_chain (depende de
-- tb_log_region_rate, que não existe neste postgres-init local) nem os
-- GRANTs de fim de arquivo (roles sys_data_engineer/sys_bi_analyst não
-- existem aqui — script-roles.sql não faz parte deste bootstrap).

CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE stage.consumption_summary (
      id                    BIGSERIAL     PRIMARY KEY
    , mongo_id              CHAR(24)      UNIQUE
    , device_id             VARCHAR(100)  NOT NULL
    , user_id               VARCHAR(100)
    , window_started_at     TIMESTAMP     NOT NULL
    , window_finished_at    TIMESTAMP     NOT NULL
    , consumption_liters    NUMERIC(10,3) NOT NULL
      CONSTRAINT chk_stage_consumption_summary_consumption_liters
        CHECK (consumption_liters >= 0)
    , lpm_average           NUMERIC(10,3)
      CONSTRAINT chk_stage_consumption_summary_lpm_average
        CHECK (lpm_average IS NULL OR lpm_average >= 0)
    , anomaly_detected      BOOLEAN
    , loaded_at             TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE silver.dm_property (
      property_id           INTEGER       PRIMARY KEY
    , name                  VARCHAR(100)  NOT NULL
    , property_type         VARCHAR(20)   NOT NULL
    , classification_id     INTEGER       NOT NULL
    , classification_group  VARCHAR(20)   NOT NULL
    , region_id             INTEGER       NOT NULL
    , city                  VARCHAR(60)   NOT NULL
    , state                 VARCHAR(30)   NOT NULL
    , built_area_m2         NUMERIC(10,2)
    , organization_id       INTEGER
    , organization_name     VARCHAR(150)
    , has_operational_profile BOOLEAN     NOT NULL DEFAULT FALSE
    , main_water_source     VARCHAR(20)
);

CREATE TABLE silver.dm_person (
      user_id               INTEGER     PRIMARY KEY
    , name                  VARCHAR(100) NOT NULL
);

CREATE TABLE silver.ft_consumption_reading (
      id                    BIGSERIAL     PRIMARY KEY
    , property_id           INTEGER       NOT NULL
    , device_id             VARCHAR(100)  NOT NULL
    , read_at               TIMESTAMP     NOT NULL
    , volume_liters         NUMERIC(10,3) NOT NULL
    , flow_lmin             NUMERIC(10,3) NOT NULL
    , CONSTRAINT uq_silver_ft_consumption_reading_device_read_at
        UNIQUE (device_id, read_at)
);

CREATE TABLE silver.ft_consumption_daily (
      id                    BIGSERIAL     PRIMARY KEY
    , property_id           INTEGER       NOT NULL
    , consumption_day       DATE          NOT NULL
    , total_liters          NUMERIC(12,3) NOT NULL
    , avg_flow_lmin         NUMERIC(10,3) NOT NULL
    , CONSTRAINT uq_silver_ft_consumption_daily_property_day
        UNIQUE (property_id, consumption_day)
);

CREATE TABLE silver.ft_water_bill (
      id                    BIGSERIAL     PRIMARY KEY
    , user_id               INTEGER       NOT NULL
    , user_name             VARCHAR(100)  NOT NULL
    , bill_month            DATE          NOT NULL
    , total_value           NUMERIC(10,2) NOT NULL
    , m3_value              NUMERIC(10,2) NOT NULL
    , CONSTRAINT uq_silver_ft_water_bill_user_month
        UNIQUE (user_id, bill_month)
);

CREATE OR REPLACE PROCEDURE silver.sp_load_dm_property()
LANGUAGE plpgsql
AS $$
BEGIN

    TRUNCATE TABLE silver.dm_property;

    INSERT INTO silver.dm_property
    (
          property_id, name, property_type, classification_id, classification_group
        , region_id, city, state, built_area_m2
        , organization_id, organization_name
        , has_operational_profile, main_water_source
    )
    SELECT
          p.id
        , p.name
        , p.type
        , p.classification_id
        , pc.group_name
        , a.region_id
        , a.city
        , a.state
        , p.built_area_m2
        , p.organization_id
        , o.trade_name
        , (op.property_id IS NOT NULL)
        , op.main_water_source
    FROM tb_property p
    JOIN tb_property_classification pc ON pc.id = p.classification_id
    JOIN tb_address a                  ON a.id = p.address_id
    LEFT JOIN tb_organization o        ON o.id = p.organization_id
    LEFT JOIN tb_property_operational_profile op ON op.property_id = p.id;

END;
$$;

CREATE OR REPLACE PROCEDURE silver.sp_load_dm_person()
LANGUAGE plpgsql
AS $$
BEGIN

    TRUNCATE TABLE silver.dm_person;

    INSERT INTO silver.dm_person (user_id, name)
    SELECT id, name
    FROM tb_user;

END;
$$;

CREATE OR REPLACE PROCEDURE silver.sp_load_ft_consumption_reading()
LANGUAGE plpgsql
AS $$
BEGIN

    INSERT INTO silver.ft_consumption_reading (property_id, device_id, read_at, volume_liters, flow_lmin)
    SELECT
          d.property_id
        , s.device_id
        , s.window_started_at
        , s.consumption_liters
        , COALESCE(s.lpm_average, 0)
    FROM stage.consumption_summary s
    JOIN tb_device d ON d.device_id = s.device_id
    ON CONFLICT (device_id, read_at) DO NOTHING;

END;
$$;

CREATE OR REPLACE PROCEDURE silver.sp_load_ft_consumption_daily()
LANGUAGE plpgsql
AS $$
BEGIN

    WITH daily AS (
        SELECT
              property_id
            , DATE(read_at)       AS consumption_day
            , SUM(volume_liters)  AS total_liters
            , AVG(flow_lmin)      AS avg_flow_lmin
        FROM silver.ft_consumption_reading
        GROUP BY property_id, DATE(read_at)
    )
    INSERT INTO silver.ft_consumption_daily (property_id, consumption_day, total_liters, avg_flow_lmin)
    SELECT property_id, consumption_day, total_liters, avg_flow_lmin
    FROM daily
    ON CONFLICT (property_id, consumption_day) DO UPDATE
        SET total_liters  = EXCLUDED.total_liters
          , avg_flow_lmin = EXCLUDED.avg_flow_lmin;

END;
$$;

CREATE OR REPLACE PROCEDURE silver.sp_load_ft_water_bill()
LANGUAGE plpgsql
AS $$
BEGIN

    INSERT INTO silver.ft_water_bill (user_id, user_name, bill_month, total_value, m3_value)
    SELECT b.user_id, u.name, b.month, b.total_value, b.m3_value
    FROM tb_last_water_bill b
    JOIN tb_user u ON u.id = b.user_id
    ON CONFLICT (user_id, bill_month) DO UPDATE
        SET total_value = EXCLUDED.total_value
          , m3_value     = EXCLUDED.m3_value;

END;
$$;

CREATE OR REPLACE PROCEDURE silver.sp_load()
LANGUAGE plpgsql
AS $$
BEGIN

    CALL silver.sp_load_ft_consumption_reading();
    CALL silver.sp_load_ft_consumption_daily();
    CALL silver.sp_load_dm_property();
    CALL silver.sp_load_dm_person();
    CALL silver.sp_load_ft_water_bill();

END;
$$;

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE gold.dm_date (
      date_key              INTEGER     PRIMARY KEY
    , full_date             DATE        NOT NULL UNIQUE
    , day_of_week           SMALLINT    NOT NULL
    , day_name              VARCHAR(20) NOT NULL
    , week_of_year          SMALLINT    NOT NULL
    , month_number          SMALLINT    NOT NULL
    , quarter_number        SMALLINT    NOT NULL
    , year_number           SMALLINT    NOT NULL
    , is_weekend            BOOLEAN     NOT NULL
);

CREATE TABLE gold.dm_property (
      property_key            SERIAL      PRIMARY KEY
    , property_id             INTEGER     NOT NULL UNIQUE
    , name                    VARCHAR(100) NOT NULL
    , property_type           VARCHAR(20) NOT NULL
    , classification_group    VARCHAR(20) NOT NULL
    , city                    VARCHAR(60) NOT NULL
    , state                   VARCHAR(30) NOT NULL
    , built_area_m2           NUMERIC(10,2)
    , organization_name       VARCHAR(150)
    , has_operational_profile BOOLEAN     NOT NULL
);

CREATE TABLE gold.dm_person (
      person_key            SERIAL      PRIMARY KEY
    , user_id               INTEGER     NOT NULL UNIQUE
    , name                  VARCHAR(100) NOT NULL
);

CREATE TABLE gold.ft_consumption_daily (
      fact_key              BIGSERIAL     PRIMARY KEY
    , property_key          INTEGER       NOT NULL
    , date_key              INTEGER       NOT NULL
    , total_liters          NUMERIC(12,3) NOT NULL
    , avg_flow_lmin         NUMERIC(10,3) NOT NULL
    , cost_value            NUMERIC(12,2) NOT NULL
    , CONSTRAINT uq_gold_ft_consumption_daily_property_date
        UNIQUE (property_key, date_key)
    , CONSTRAINT fk_gold_ft_consumption_daily_property
        FOREIGN KEY (property_key) REFERENCES gold.dm_property (property_key)
    , CONSTRAINT fk_gold_ft_consumption_daily_date
        FOREIGN KEY (date_key) REFERENCES gold.dm_date (date_key)
);

CREATE TABLE gold.ft_water_bill_monthly (
      fact_key              BIGSERIAL     PRIMARY KEY
    , person_key            INTEGER       NOT NULL
    , date_key              INTEGER       NOT NULL
    , total_value           NUMERIC(10,2) NOT NULL
    , m3_value              NUMERIC(10,2) NOT NULL
    , CONSTRAINT uq_gold_ft_water_bill_monthly_person_date
        UNIQUE (person_key, date_key)
    , CONSTRAINT fk_gold_ft_water_bill_monthly_person
        FOREIGN KEY (person_key) REFERENCES gold.dm_person (person_key)
    , CONSTRAINT fk_gold_ft_water_bill_monthly_date
        FOREIGN KEY (date_key) REFERENCES gold.dm_date (date_key)
);

CREATE TABLE gold.ft_investment_scenario (
      scenario_key          SERIAL        PRIMARY KEY
    , scenario_id           INTEGER       NOT NULL UNIQUE
    , name                  VARCHAR(100)  NOT NULL
    , investment_value      NUMERIC(10,2) NOT NULL
    , reduction_pct         NUMERIC(5,2)  NOT NULL
    , annual_savings_value  NUMERIC(10,2) NOT NULL
    , payback_months        NUMERIC(6,1)
);

CREATE OR REPLACE PROCEDURE gold.sp_load_dm_date()
LANGUAGE plpgsql
AS $$
BEGIN

    INSERT INTO gold.dm_date (date_key, full_date, day_of_week, day_name, week_of_year, month_number, quarter_number, year_number, is_weekend)
    SELECT
          TO_CHAR(d, 'YYYYMMDD')::INTEGER
        , d
        , EXTRACT(DOW FROM d)
        , TRIM(TO_CHAR(d, 'Day'))
        , EXTRACT(WEEK FROM d)
        , EXTRACT(MONTH FROM d)
        , EXTRACT(QUARTER FROM d)
        , EXTRACT(YEAR FROM d)
        , EXTRACT(DOW FROM d) IN (0, 6)
    FROM generate_series('2024-01-01'::DATE, '2028-12-31'::DATE, INTERVAL '1 day') AS d
    ON CONFLICT (date_key) DO NOTHING;

END;
$$;

CREATE OR REPLACE PROCEDURE gold.sp_load_dm_property()
LANGUAGE plpgsql
AS $$
BEGIN

    DELETE FROM gold.dm_property
    WHERE property_id NOT IN (SELECT property_id FROM silver.dm_property);

    INSERT INTO gold.dm_property (property_id, name, property_type, classification_group, city, state, built_area_m2, organization_name, has_operational_profile)
    SELECT property_id, name, property_type, classification_group, city, state, built_area_m2, organization_name, has_operational_profile
    FROM silver.dm_property
    ON CONFLICT (property_id) DO UPDATE
        SET name                     = EXCLUDED.name
          , property_type            = EXCLUDED.property_type
          , classification_group     = EXCLUDED.classification_group
          , city                     = EXCLUDED.city
          , state                    = EXCLUDED.state
          , built_area_m2            = EXCLUDED.built_area_m2
          , organization_name        = EXCLUDED.organization_name
          , has_operational_profile  = EXCLUDED.has_operational_profile;

END;
$$;

CREATE OR REPLACE PROCEDURE gold.sp_load_dm_person()
LANGUAGE plpgsql
AS $$
BEGIN

    DELETE FROM gold.dm_person
    WHERE user_id NOT IN (SELECT user_id FROM silver.dm_person);

    INSERT INTO gold.dm_person (user_id, name)
    SELECT user_id, name
    FROM silver.dm_person
    ON CONFLICT (user_id) DO UPDATE
        SET name = EXCLUDED.name;

END;
$$;

CREATE OR REPLACE PROCEDURE gold.sp_load_ft_consumption_daily()
LANGUAGE plpgsql
AS $$
BEGIN

    WITH staging_daily AS (
        SELECT
              cd.property_id
            , cd.consumption_day
            , cd.total_liters
            , cd.avg_flow_lmin
            , sp.region_id
            , sp.classification_id
        FROM silver.ft_consumption_daily cd
        JOIN silver.dm_property sp ON sp.property_id = cd.property_id
    ),
    with_cost AS (
        SELECT
              sd.*
            , ROUND(sd.total_liters / 1000.0 * r.m3_value, 2) AS cost_value
        FROM staging_daily sd
        JOIN LATERAL (
            SELECT rr.m3_value
              FROM tb_region_rate rr
             WHERE rr.region_id = sd.region_id
               AND rr.classification_id = sd.classification_id
               AND rr.initial_validity <= sd.consumption_day
               AND (rr.final_validity IS NULL OR rr.final_validity >= sd.consumption_day)
             ORDER BY rr.initial_validity DESC
             LIMIT 1
        ) r ON TRUE
    )
    INSERT INTO gold.ft_consumption_daily (property_key, date_key, total_liters, avg_flow_lmin, cost_value)
    SELECT
          dp.property_key
        , TO_CHAR(wc.consumption_day, 'YYYYMMDD')::INTEGER
        , wc.total_liters
        , wc.avg_flow_lmin
        , wc.cost_value
    FROM with_cost wc
    JOIN gold.dm_property dp ON dp.property_id = wc.property_id
    ON CONFLICT (property_key, date_key) DO UPDATE
        SET total_liters  = EXCLUDED.total_liters
          , avg_flow_lmin = EXCLUDED.avg_flow_lmin
          , cost_value    = EXCLUDED.cost_value;

END;
$$;

CREATE OR REPLACE PROCEDURE gold.sp_load_ft_water_bill_monthly()
LANGUAGE plpgsql
AS $$
BEGIN

    INSERT INTO gold.ft_water_bill_monthly (person_key, date_key, total_value, m3_value)
    SELECT
          dp.person_key
        , TO_CHAR(wb.bill_month, 'YYYYMMDD')::INTEGER
        , wb.total_value
        , wb.m3_value
    FROM silver.ft_water_bill wb
    JOIN gold.dm_person dp ON dp.user_id = wb.user_id
    ON CONFLICT (person_key, date_key) DO UPDATE
        SET total_value = EXCLUDED.total_value
          , m3_value    = EXCLUDED.m3_value;

END;
$$;

CREATE OR REPLACE PROCEDURE gold.sp_load_ft_investment_scenario()
LANGUAGE plpgsql
AS $$
BEGIN

    INSERT INTO gold.ft_investment_scenario (scenario_id, name, investment_value, reduction_pct, annual_savings_value, payback_months)
    SELECT id, name, investment_value, reduction_pct, annual_savings_value, payback_months
    FROM tb_investment_scenario
    ON CONFLICT (scenario_id) DO UPDATE
        SET name                 = EXCLUDED.name
          , investment_value     = EXCLUDED.investment_value
          , reduction_pct        = EXCLUDED.reduction_pct
          , annual_savings_value = EXCLUDED.annual_savings_value
          , payback_months       = EXCLUDED.payback_months;

END;
$$;

CREATE OR REPLACE PROCEDURE gold.sp_load()
LANGUAGE plpgsql
AS $$
BEGIN

    CALL gold.sp_load_dm_date();
    CALL gold.sp_load_dm_property();
    CALL gold.sp_load_dm_person();
    CALL gold.sp_load_ft_consumption_daily();
    CALL gold.sp_load_ft_water_bill_monthly();
    CALL gold.sp_load_ft_investment_scenario();

END;
$$;

CREATE SCHEMA IF NOT EXISTS dw;

CREATE OR REPLACE VIEW dw.vw_ft_consumption_daily AS
WITH staging_consumption AS (
    SELECT
          f.property_key
        , dp.property_id
        , dp.name           AS property_name
        , dd.full_date
        , f.total_liters
        , f.cost_value
    FROM gold.ft_consumption_daily f
    JOIN gold.dm_property dp ON dp.property_key = f.property_key
    JOIN gold.dm_date dd     ON dd.date_key = f.date_key
)
SELECT
      property_id
    , property_name
    , full_date
    , total_liters
    , cost_value
    , SUM(total_liters) OVER (
          PARTITION BY property_id ORDER BY full_date
          ROWS UNBOUNDED PRECEDING
      ) AS running_total_liters
    , AVG(total_liters) OVER (
          PARTITION BY property_id ORDER BY full_date
          ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
      ) AS moving_avg_7d_liters
FROM staging_consumption;

CREATE OR REPLACE VIEW dw.vw_ft_property_ranking AS
WITH agg_consumption AS (
    SELECT
          dp.property_id
        , dp.name             AS property_name
        , dp.built_area_m2
        , SUM(f.total_liters) AS total_liters
        , SUM(f.cost_value)   AS total_cost
    FROM gold.ft_consumption_daily f
    JOIN gold.dm_property dp ON dp.property_key = f.property_key
    WHERE dp.built_area_m2 IS NOT NULL
    GROUP BY dp.property_id, dp.name, dp.built_area_m2
),
final_ranking AS (
    SELECT
          property_id
        , property_name
        , total_liters
        , total_cost
        , ROUND(total_liters / built_area_m2, 2) AS liters_per_m2
    FROM agg_consumption
)
SELECT
      property_id
    , property_name
    , total_liters
    , total_cost
    , liters_per_m2
    , RANK()         OVER (ORDER BY liters_per_m2 ASC)  AS rank_efficiency
    , DENSE_RANK()   OVER (ORDER BY total_cost DESC)    AS rank_cost
    , NTILE(4)       OVER (ORDER BY liters_per_m2)      AS consumption_quartile
    , PERCENT_RANK() OVER (ORDER BY liters_per_m2)      AS consumption_percent_rank
FROM final_ranking;

CREATE OR REPLACE VIEW dw.vw_ft_monthly_variation AS
WITH staging_monthly AS (
    SELECT
          dp.property_id
        , dp.name AS property_name
        , DATE_TRUNC('month', dd.full_date)::DATE AS reference_month
        , SUM(f.total_liters) AS total_liters
    FROM gold.ft_consumption_daily f
    JOIN gold.dm_property dp ON dp.property_key = f.property_key
    JOIN gold.dm_date dd     ON dd.date_key = f.date_key
    GROUP BY dp.property_id, dp.name, DATE_TRUNC('month', dd.full_date)
),
final_variation AS (
    SELECT
          property_id
        , property_name
        , reference_month
        , total_liters
        , LAG(total_liters) OVER (PARTITION BY property_id ORDER BY reference_month) AS previous_month_liters
    FROM staging_monthly
)
SELECT
      property_id
    , property_name
    , reference_month
    , total_liters
    , previous_month_liters
    , ROUND(
          (total_liters - previous_month_liters) / NULLIF(previous_month_liters, 0) * 100
        , 1
      ) AS variation_pct
FROM final_variation;

CREATE OR REPLACE VIEW dw.vw_ft_consumption_distribution AS
WITH staging_daily_totals AS (
    SELECT
          f.property_key
        , f.total_liters
    FROM gold.ft_consumption_daily f
),
agg_stats AS (
    SELECT
          MIN(total_liters) AS min_liters
        , MAX(total_liters) AS max_liters
        , PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY total_liters) AS q1_liters
        , PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_liters) AS median_liters
        , PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY total_liters) AS q3_liters
    FROM staging_daily_totals
)
SELECT
      s.property_key
    , s.total_liters
    , NTILE(5) OVER (ORDER BY s.total_liters) AS distribution_bucket
    , a.min_liters
    , a.q1_liters
    , a.median_liters
    , a.q3_liters
    , a.max_liters
FROM staging_daily_totals s
CROSS JOIN agg_stats a;

CREATE OR REPLACE VIEW dw.vw_ft_capex_comparison AS
WITH staging_scenario AS (
    SELECT
          scenario_id
        , name
        , investment_value
        , reduction_pct
        , annual_savings_value
        , payback_months
    FROM gold.ft_investment_scenario
)
SELECT
      scenario_id
    , name
    , investment_value
    , reduction_pct
    , annual_savings_value
    , payback_months
    , RANK() OVER (ORDER BY payback_months ASC NULLS LAST) AS rank_by_payback
FROM staging_scenario;

CREATE OR REPLACE VIEW dw.vw_ft_residential_efficiency_ranking AS
WITH staging_bill AS (
    SELECT
          dpe.user_id
        , dpe.name AS person_name
        , dd.full_date AS reference_month
        , f.m3_value
        , f.total_value
    FROM gold.ft_water_bill_monthly f
    JOIN gold.dm_person dpe ON dpe.person_key = f.person_key
    JOIN gold.dm_date dd    ON dd.date_key = f.date_key
)
SELECT
      user_id
    , person_name
    , reference_month
    , m3_value
    , total_value
    , RANK()         OVER (PARTITION BY reference_month ORDER BY m3_value ASC) AS rank_efficiency
    , PERCENT_RANK() OVER (PARTITION BY reference_month ORDER BY m3_value)     AS consumption_percent_rank
FROM staging_bill;
