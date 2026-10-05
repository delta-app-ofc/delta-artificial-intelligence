-- Cópia read-only do schema de organização do delta-sql-database
-- (branch feat/data-mart-industrial-bi). organization_id/built_area_m2 em
-- tb_property são ALTER porque 01-schema.sql já cria a tabela sem eles.

CREATE TABLE tb_organization (
      id                     SERIAL       PRIMARY KEY
    , corporate_name         VARCHAR(150) NOT NULL
    , trade_name             VARCHAR(150) NOT NULL
    , cnpj                   CHAR(14)     NOT NULL
      CONSTRAINT chk_tb_organization_cnpj CHECK (cnpj ~ '^[0-9]{14}$')
    , business_segment       VARCHAR(20)  NOT NULL
      CONSTRAINT chk_tb_organization_business_segment
        CHECK (business_segment IN ('VAREJO', 'INDUSTRIA', 'CONDOMINIO', 'FACILITIES'))
    , declared_unit_count    INTEGER
      CONSTRAINT chk_tb_organization_declared_unit_count
        CHECK (declared_unit_count IS NULL OR declared_unit_count > 0)
    , registration_date      DATE         NOT NULL DEFAULT CURRENT_DATE
    , CONSTRAINT uq_tb_organization_cnpj UNIQUE (cnpj)
);

CREATE TABLE tb_user_organization (
      id                SERIAL  PRIMARY KEY
    , user_id           INTEGER NOT NULL
    , organization_id   INTEGER NOT NULL
    , association_date  DATE    NOT NULL DEFAULT CURRENT_DATE
    , CONSTRAINT uq_tb_user_organization UNIQUE (user_id, organization_id)
    , CONSTRAINT fk_tb_user_organization_user FOREIGN KEY (user_id)
        REFERENCES tb_user (id) ON DELETE CASCADE ON UPDATE CASCADE
    , CONSTRAINT fk_tb_user_organization_org FOREIGN KEY (organization_id)
        REFERENCES tb_organization (id) ON DELETE CASCADE ON UPDATE CASCADE
);

ALTER TABLE tb_property
    ADD COLUMN organization_id INTEGER,
    ADD COLUMN built_area_m2 NUMERIC(10,2)
        CONSTRAINT chk_tb_property_built_area_m2 CHECK (built_area_m2 IS NULL OR built_area_m2 > 0),
    ADD CONSTRAINT fk_tb_property_organization FOREIGN KEY (organization_id)
        REFERENCES tb_organization (id) ON DELETE RESTRICT ON UPDATE CASCADE;

CREATE TABLE tb_property_operational_profile (
      property_id       INTEGER     PRIMARY KEY
    , main_water_source VARCHAR(20) NOT NULL
      CONSTRAINT chk_tb_property_operational_profile_main_water_source
        CHECK (main_water_source IN ('CONCESSIONARIA', 'POCO_ARTESIANO', 'CISTERNA', 'REUSO'))
    , CONSTRAINT fk_tb_property_operational_profile_property FOREIGN KEY (property_id)
        REFERENCES tb_property (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE tb_property_shift (
      id          SERIAL  PRIMARY KEY
    , property_id INTEGER NOT NULL
    , start_time  TIME    NOT NULL
    , end_time    TIME    NOT NULL
      CONSTRAINT chk_tb_property_shift_end_after_start CHECK (end_time > start_time)
    , CONSTRAINT fk_tb_property_shift_property FOREIGN KEY (property_id)
        REFERENCES tb_property (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE tb_water_usage_type (
      id          SERIAL      PRIMARY KEY
    , name        VARCHAR(30) NOT NULL UNIQUE
      CONSTRAINT chk_tb_water_usage_type_name_values
        CHECK (name IN ('LIMPEZA', 'CONSUMO_HUMANO', 'PROCESSO_PRODUTIVO', 'IRRIGACAO'))
    , description TEXT
);

CREATE TABLE tb_property_water_usage (
      id                  SERIAL  PRIMARY KEY
    , property_id         INTEGER NOT NULL
    , water_usage_type_id INTEGER NOT NULL
    , CONSTRAINT uq_tb_property_water_usage UNIQUE (property_id, water_usage_type_id)
    , CONSTRAINT fk_tb_property_water_usage_property FOREIGN KEY (property_id)
        REFERENCES tb_property (id) ON DELETE CASCADE ON UPDATE CASCADE
    , CONSTRAINT fk_tb_property_water_usage_type FOREIGN KEY (water_usage_type_id)
        REFERENCES tb_water_usage_type (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE tb_property_operation_day (
      id             SERIAL  PRIMARY KEY
    , property_id    INTEGER NOT NULL
    , day_of_week_id INTEGER NOT NULL
    , CONSTRAINT uq_tb_property_operation_day UNIQUE (property_id, day_of_week_id)
    , CONSTRAINT fk_tb_property_operation_day_property FOREIGN KEY (property_id)
        REFERENCES tb_property (id) ON DELETE CASCADE ON UPDATE CASCADE
    , CONSTRAINT fk_tb_property_operation_day_day_of_week FOREIGN KEY (day_of_week_id)
        REFERENCES tb_day_of_week (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE tb_investment_scenario (
      id                    SERIAL        PRIMARY KEY
    , organization_id       INTEGER
    , name                  VARCHAR(100)  NOT NULL
    , investment_value      NUMERIC(10,2) NOT NULL CHECK (investment_value >= 0)
    , reduction_pct         NUMERIC(5,2)  NOT NULL CHECK (reduction_pct BETWEEN 0 AND 100)
    , annual_savings_value  NUMERIC(10,2) NOT NULL CHECK (annual_savings_value >= 0)
    , payback_months        NUMERIC(6,1)          CHECK (payback_months IS NULL OR payback_months >= 0)
    , description           TEXT
    , CONSTRAINT fk_tb_investment_scenario_organization FOREIGN KEY (organization_id)
        REFERENCES tb_organization (id) ON DELETE CASCADE ON UPDATE CASCADE
);
