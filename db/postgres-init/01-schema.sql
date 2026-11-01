DROP TABLE IF EXISTS tb_data_catalog      CASCADE;
DROP TABLE IF EXISTS tb_backup_restore_log CASCADE;
DROP TABLE IF EXISTS tb_log_rpa           CASCADE;
DROP TABLE IF EXISTS tb_investment_scenario CASCADE;
DROP TABLE IF EXISTS tb_user_access_log   CASCADE;
DROP TABLE IF EXISTS tb_last_water_bill   CASCADE;
DROP TABLE IF EXISTS tb_user_habit_day    CASCADE;
DROP TABLE IF EXISTS tb_user_habit        CASCADE;
DROP TABLE IF EXISTS tb_region_rate       CASCADE;
DROP TABLE IF EXISTS tb_device            CASCADE;
DROP TABLE IF EXISTS tb_user_organization CASCADE;
DROP TABLE IF EXISTS tb_user_property     CASCADE;
DROP TABLE IF EXISTS tb_property_operation_day CASCADE;
DROP TABLE IF EXISTS tb_property_water_usage CASCADE;
DROP TABLE IF EXISTS tb_property_shift    CASCADE;
DROP TABLE IF EXISTS tb_property_operational_profile CASCADE;
DROP TABLE IF EXISTS tb_property          CASCADE;
DROP TABLE IF EXISTS tb_organization      CASCADE;
DROP TABLE IF EXISTS tb_property_classification CASCADE;
DROP TABLE IF EXISTS tb_user              CASCADE;
DROP TABLE IF EXISTS tb_address           CASCADE;
DROP TABLE IF EXISTS tb_water_usage_type  CASCADE;
DROP TABLE IF EXISTS tb_habit             CASCADE;
DROP TABLE IF EXISTS tb_day_of_week       CASCADE;
DROP TABLE IF EXISTS tb_municipality      CASCADE;
DROP TABLE IF EXISTS tb_region            CASCADE;


CREATE TABLE tb_region (
      id                                   SERIAL      PRIMARY KEY
    , name                                 VARCHAR(30) NOT NULL UNIQUE
      CONSTRAINT chk_tb_region_name_values CHECK (name IN ('GRANDE_SP', 'LINS', 'PRESIDENTE_PRUDENTE', 'ADAMANTINA_PIRAPOZINHO', 'BRAGANCA_PAULISTA', 'LITORAL', 'VALE_DO_RIBEIRA', 'INTERIOR', 'VALE_DO_PARAIBA'))
);

CREATE TABLE tb_municipality (
      id                                 SERIAL      PRIMARY KEY
    , name                               VARCHAR(60) NOT NULL UNIQUE
    , ibge_code                          INTEGER     NOT NULL UNIQUE
      CONSTRAINT chk_tb_municipality_ibge_code CHECK (ibge_code BETWEEN 3500000 AND 3599999)
    , region_id                          INTEGER     NOT NULL
    , CONSTRAINT fk_tb_municipality_region FOREIGN KEY (region_id)
        REFERENCES tb_region (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
);

CREATE TABLE tb_day_of_week (
      id                                        SERIAL      PRIMARY KEY
    , name                                      VARCHAR(20) NOT NULL UNIQUE
      CONSTRAINT chk_tb_day_of_week_name_values CHECK (name IN ('SEGUNDA', 'TERÇA', 'QUARTA', 'QUINTA', 'SEXTA', 'SÁBADO', 'DOMINGO'))
);

CREATE TABLE tb_habit (
      id                                      SERIAL      PRIMARY KEY
    , name                                    VARCHAR(30) NOT NULL UNIQUE
      CONSTRAINT chk_tb_habit_name_values     CHECK (name IN ('BANHO LONGO', 'LAVAR QUINTAL', 'LAVAR ROUPA', 'REGAR PLANTAS', 'LAVAR CARRO', 'LAVAR LOUÇA'))
    , category                                VARCHAR(30) NOT NULL
      CONSTRAINT chk_tb_habit_category_values CHECK (category IN ('HIGIENE E CUIDADOS', 'LIMPEZA', 'JARDINAGEM'))
    , description                             TEXT
);

CREATE TABLE tb_water_usage_type (
      id                                          SERIAL      PRIMARY KEY
    , name                                        VARCHAR(30) NOT NULL UNIQUE
      CONSTRAINT chk_tb_water_usage_type_name_values
        CHECK (name IN ('LIMPEZA', 'CONSUMO_HUMANO', 'PROCESSO_PRODUTIVO', 'IRRIGACAO'))
    , description                                 TEXT
);

CREATE TABLE tb_address (
      id                            SERIAL      PRIMARY KEY
    , region_id                     INTEGER     NOT NULL
    , cep                           CHAR(8)     NOT NULL
      CONSTRAINT chk_tb_address_cep CHECK      (cep ~ '^[0-9]{8}$')
    , city                          VARCHAR(60) NOT NULL
    , state                         VARCHAR(30) NOT NULL
    , latitude                      NUMERIC(8,6)
      CONSTRAINT chk_tb_address_latitude  CHECK (latitude  BETWEEN -90  AND 90)
    , longitude                     NUMERIC(9,6)
      CONSTRAINT chk_tb_address_longitude CHECK (longitude BETWEEN -180 AND 180)
    , CONSTRAINT uq_tb_address_cep              UNIQUE (cep)
    , CONSTRAINT fk_tb_address_region           FOREIGN KEY (region_id)
        REFERENCES tb_region (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
);

CREATE TABLE tb_user (
      id                    SERIAL       PRIMARY KEY
    , name                  VARCHAR(100) NOT NULL
    , email                 VARCHAR(255) NOT NULL UNIQUE
    , password              VARCHAR(255) NOT NULL
    , phone                 VARCHAR(15)
    , birth_date            DATE         NOT NULL
    , CONSTRAINT chk_tb_user_birth_date
        CHECK (birth_date <= CURRENT_DATE - INTERVAL '18 years')    , registration_date     DATE         NOT NULL DEFAULT CURRENT_DATE
    , is_active             BOOLEAN      NOT NULL DEFAULT TRUE
    , is_admin              BOOLEAN      NOT NULL DEFAULT FALSE
    , is_manager            BOOLEAN      NOT NULL DEFAULT FALSE
);

CREATE TABLE tb_property_classification (
      id                                                SERIAL      PRIMARY KEY
    , name                                              VARCHAR(50) NOT NULL UNIQUE
      CONSTRAINT chk_tb_property_classification_name
        CHECK (name IN ('RESIDENCIAL_NORMAL', 'RESIDENCIAL_SOCIAL', 'RESIDENCIAL_FAVELA', 'RESIDENCIAL_ESPECIAL', 'COMERCIAL_NORMAL_INDUSTRIAL', 'COMERCIAL_ESPECIAL', 'COMERCIAL_ENTIDADE_ASSISTENCIA_SOCIAL', 'PUBLICA_COM_CONTRATO'))
    , group_name                                        VARCHAR(20) NOT NULL
      CONSTRAINT chk_tb_property_classification_group   CHECK (group_name IN ('RESIDENCIAL', 'COMERCIAL'))
);

CREATE TABLE tb_organization (
      id                                        SERIAL       PRIMARY KEY
    , corporate_name                            VARCHAR(150) NOT NULL
    , trade_name                                VARCHAR(150) NOT NULL
    , cnpj                                       CHAR(14)     NOT NULL
      CONSTRAINT chk_tb_organization_cnpj CHECK (cnpj ~ '^[0-9]{14}$')
    , business_segment                          VARCHAR(20)  NOT NULL
      CONSTRAINT chk_tb_organization_business_segment
        CHECK (business_segment IN ('VAREJO', 'INDUSTRIA', 'CONDOMINIO', 'FACILITIES'))
    , declared_unit_count                       INTEGER
      CONSTRAINT chk_tb_organization_declared_unit_count
        CHECK (declared_unit_count IS NULL OR declared_unit_count > 0)
    , registration_date                         DATE         NOT NULL DEFAULT CURRENT_DATE
    , CONSTRAINT uq_tb_organization_cnpj                     UNIQUE (cnpj)
);

CREATE TABLE tb_property (
      id                    SERIAL              PRIMARY KEY
    , name                  VARCHAR(100)        NOT NULL
    , type                  VARCHAR(20)         NOT NULL
      CONSTRAINT chk_tb_property_type           CHECK (type IN ('CASA', 'PRÉDIO'))
    , classification_id     INTEGER             NOT NULL
    , address_id            INTEGER             NOT NULL
    , organization_id       INTEGER
    , built_area_m2         NUMERIC(10,2)
      CONSTRAINT chk_tb_property_built_area_m2
        CHECK (built_area_m2 IS NULL OR built_area_m2 > 0)
    , registration_date     DATE                NOT NULL DEFAULT CURRENT_DATE
    , CONSTRAINT uq_tb_property_name_address    UNIQUE (name, address_id)
    , CONSTRAINT fk_tb_property_classification  FOREIGN KEY (classification_id)
        REFERENCES tb_property_classification (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
    , CONSTRAINT fk_tb_property_address         FOREIGN KEY (address_id)
        REFERENCES tb_address (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
    , CONSTRAINT fk_tb_property_organization    FOREIGN KEY (organization_id)
        REFERENCES tb_organization (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
);

CREATE TABLE tb_property_operational_profile (
      property_id           INTEGER     PRIMARY KEY
    , main_water_source     VARCHAR(20) NOT NULL
      CONSTRAINT chk_tb_property_operational_profile_main_water_source
        CHECK (main_water_source IN ('CONCESSIONARIA', 'POCO_ARTESIANO', 'CISTERNA', 'REUSO'))
    , CONSTRAINT fk_tb_property_operational_profile_property
        FOREIGN KEY (property_id)
        REFERENCES tb_property (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_property_shift (
      id                    SERIAL      PRIMARY KEY
    , property_id           INTEGER     NOT NULL
    , start_time            TIME        NOT NULL
    , end_time              TIME        NOT NULL
      CONSTRAINT chk_tb_property_shift_end_after_start
        CHECK (end_time > start_time)
    , CONSTRAINT fk_tb_property_shift_property
        FOREIGN KEY (property_id)
        REFERENCES tb_property (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_property_water_usage (
      id                            SERIAL      PRIMARY KEY
    , property_id                   INTEGER     NOT NULL
    , water_usage_type_id           INTEGER     NOT NULL
    , CONSTRAINT uq_tb_property_water_usage
        UNIQUE (property_id, water_usage_type_id)
    , CONSTRAINT fk_tb_property_water_usage_property
        FOREIGN KEY (property_id)
        REFERENCES tb_property (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
    , CONSTRAINT fk_tb_property_water_usage_type
        FOREIGN KEY (water_usage_type_id)
        REFERENCES tb_water_usage_type (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_property_operation_day (
      id                            SERIAL      PRIMARY KEY
    , property_id                   INTEGER     NOT NULL
    , day_of_week_id                INTEGER     NOT NULL
    , CONSTRAINT uq_tb_property_operation_day
        UNIQUE (property_id, day_of_week_id)
    , CONSTRAINT fk_tb_property_operation_day_property
        FOREIGN KEY (property_id)
        REFERENCES tb_property (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
    , CONSTRAINT fk_tb_property_operation_day_day_of_week
        FOREIGN KEY (day_of_week_id)
        REFERENCES tb_day_of_week (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_user_property (
      id                                      SERIAL      PRIMARY KEY
    , user_id                                 INTEGER     NOT NULL
    , property_id                             INTEGER     NOT NULL
    , association_date                        DATE        NOT NULL DEFAULT CURRENT_DATE
    , CONSTRAINT uq_tb_user_property          UNIQUE     (user_id, property_id)
    , CONSTRAINT fk_tb_user_property_user     FOREIGN KEY (user_id)
        REFERENCES tb_user (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
    , CONSTRAINT fk_tb_user_property_property FOREIGN KEY (property_id)
        REFERENCES tb_property (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_user_organization (
      id                                          SERIAL      PRIMARY KEY
    , user_id                                     INTEGER     NOT NULL
    , organization_id                             INTEGER     NOT NULL
    , association_date                            DATE        NOT NULL DEFAULT CURRENT_DATE
    , CONSTRAINT uq_tb_user_organization           UNIQUE     (user_id, organization_id)
    , CONSTRAINT fk_tb_user_organization_user      FOREIGN KEY (user_id)
        REFERENCES tb_user (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
    , CONSTRAINT fk_tb_user_organization_org       FOREIGN KEY (organization_id)
        REFERENCES tb_organization (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_device (
      id                    SERIAL      PRIMARY KEY
    , device_id             VARCHAR(100) NOT NULL UNIQUE
    , property_id           INTEGER      NOT NULL
    , is_active             BOOLEAN      NOT NULL DEFAULT TRUE
    , installation_date     DATE         NOT NULL DEFAULT CURRENT_DATE

    , CONSTRAINT fk_tb_device_property
        FOREIGN KEY (property_id)
        REFERENCES tb_property (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);


CREATE TABLE tb_region_rate (

      id                                          SERIAL        PRIMARY KEY

    , region_id                                   INTEGER       NOT NULL

    , classification_id                           INTEGER       NOT NULL

    , m3_value                                    NUMERIC(10,2) NOT NULL
      CONSTRAINT chk_tb_region_rate_m3_value CHECK (m3_value > 0)

    , initial_validity                            DATE          NOT NULL

    , final_validity                              DATE
      CONSTRAINT chk_tb_region_rate_final_validity
        CHECK (final_validity IS NULL OR final_validity >= initial_validity)

    , CONSTRAINT uq_tb_region_rate_region_classification_validity
        UNIQUE (region_id, classification_id, initial_validity)

    , CONSTRAINT fk_tb_region_rate_region
        FOREIGN KEY (region_id)
        REFERENCES tb_region (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE

    , CONSTRAINT fk_tb_region_rate_classification
        FOREIGN KEY (classification_id)
        REFERENCES tb_property_classification (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
);

CREATE TABLE tb_user_habit (
      id                    SERIAL          PRIMARY KEY
    , user_id               INTEGER         NOT NULL
    , habit_id              INTEGER         NOT NULL
    , frequency             INTEGER         NOT NULL
      CONSTRAINT chk_tb_user_habit_frequency
          CHECK (frequency > 0)
    , start_time            TIME
    , end_time              TIME
    , estimated_liters      NUMERIC(6, 2)
      CONSTRAINT chk_tb_user_habit_estimated_liters
          CHECK (estimated_liters IS NULL OR estimated_liters >= 0)
      CONSTRAINT chk_tb_user_habit_time
          CHECK (
              (start_time IS NULL AND end_time IS NULL)
              OR (start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time)
          )
    , CONSTRAINT fk_tb_user_habit_user
        FOREIGN KEY (user_id)
        REFERENCES tb_user (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
    , CONSTRAINT fk_tb_user_habit_habit
        FOREIGN KEY (habit_id)
        REFERENCES tb_habit (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_user_habit_day (
      id                    SERIAL      PRIMARY KEY
    , user_habit_id         INTEGER     NOT NULL
    , day_of_week_id        INTEGER     NOT NULL
    , CONSTRAINT uq_tb_user_habit_day
        UNIQUE (user_habit_id, day_of_week_id)
    , CONSTRAINT fk_tb_user_habit_day_user_habit
        FOREIGN KEY (user_habit_id)
        REFERENCES tb_user_habit (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
    , CONSTRAINT fk_tb_user_habit_day_day_of_week
        FOREIGN KEY (day_of_week_id)
        REFERENCES tb_day_of_week (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_last_water_bill (

      id                    SERIAL        PRIMARY KEY
    , user_id               INTEGER       NOT NULL

    , month                 DATE          NOT NULL
     CONSTRAINT chk_tb_last_water_bill_month
          CHECK (EXTRACT(DAY FROM month) = 1)

    , total_value           NUMERIC(10,2) NOT NULL
      CONSTRAINT chk_tb_last_water_bill_total_value
          CHECK (total_value >= 0)

    , m3_value              NUMERIC(10,2) NOT NULL
      CONSTRAINT chk_tb_last_water_bill_m3_value
          CHECK (m3_value >= 0)

    , CONSTRAINT uq_tb_last_water_bill_user_month
        UNIQUE (user_id, month)

    , CONSTRAINT fk_tb_last_water_bill_user
        FOREIGN KEY (user_id)
        REFERENCES tb_user (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_investment_scenario (
      id                                            SERIAL        PRIMARY KEY
    , organization_id                               INTEGER
    , name                                          VARCHAR(100)  NOT NULL
    , investment_value                              NUMERIC(10,2) NOT NULL
      CONSTRAINT chk_tb_investment_scenario_investment_value
        CHECK (investment_value >= 0)
    , reduction_pct                                 NUMERIC(5,2)  NOT NULL
      CONSTRAINT chk_tb_investment_scenario_reduction_pct
        CHECK (reduction_pct >= 0 AND reduction_pct <= 100)
    , annual_savings_value                          NUMERIC(10,2) NOT NULL
      CONSTRAINT chk_tb_investment_scenario_annual_savings_value
        CHECK (annual_savings_value >= 0)
    , payback_months                                NUMERIC(6,1)
      CONSTRAINT chk_tb_investment_scenario_payback_months
        CHECK (payback_months IS NULL OR payback_months >= 0)
    , description                                   TEXT
    , CONSTRAINT fk_tb_investment_scenario_organization
        FOREIGN KEY (organization_id)
        REFERENCES tb_organization (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_user_access_log (

      id                    SERIAL       PRIMARY KEY
    , user_id               INTEGER      NOT NULL

    , access_channel        VARCHAR(20)
      CONSTRAINT chk_tb_user_access_log_access_channel
          CHECK (access_channel IN ('WEB', 'MOBILE', 'CHATBOT'))

    , accessed_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP

    , CONSTRAINT fk_tb_user_access_log_user
        FOREIGN KEY (user_id)
        REFERENCES tb_user (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE tb_log_rpa (

      id                       SERIAL      PRIMARY KEY

    , started_at               TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
    , finished_at              TIMESTAMP

    , status                   VARCHAR(10) NOT NULL DEFAULT 'RUNNING'
      CONSTRAINT chk_tb_log_rpa_status
          CHECK (status IN ('RUNNING', 'SUCCESS', 'ERROR'))

    , inserted_count           INTEGER     NOT NULL DEFAULT 0
      CONSTRAINT chk_tb_log_rpa_inserted_count          CHECK (inserted_count >= 0)

    , updated_count            INTEGER     NOT NULL DEFAULT 0
      CONSTRAINT chk_tb_log_rpa_updated_count           CHECK (updated_count >= 0)

    , deleted_count            INTEGER     NOT NULL DEFAULT 0
      CONSTRAINT chk_tb_log_rpa_deleted_count           CHECK (deleted_count >= 0)

    , validation_error_count   INTEGER     NOT NULL DEFAULT 0
      CONSTRAINT chk_tb_log_rpa_validation_error_count  CHECK (validation_error_count >= 0)

    , error_message            TEXT
);

CREATE TABLE tb_data_catalog (
      id                    SERIAL      PRIMARY KEY
    , table_name            VARCHAR(60) NOT NULL
    , column_name           VARCHAR(60) NOT NULL
    , data_type             VARCHAR(60) NOT NULL
    , description           TEXT        NOT NULL
    , business_rule         TEXT
    , access_level          VARCHAR(20) NOT NULL
      CONSTRAINT chk_tb_data_catalog_access_level
        CHECK (access_level IN ('PUBLICO', 'INTERNO', 'RESTRITO', 'SENSIVEL'))
    , CONSTRAINT uq_tb_data_catalog_table_column
        UNIQUE (table_name, column_name)
);

CREATE TABLE tb_backup_restore_log (

      id                       SERIAL      PRIMARY KEY

    , started_at               TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
    , finished_at              TIMESTAMP

    , status                   VARCHAR(10) NOT NULL DEFAULT 'RUNNING'
      CONSTRAINT chk_tb_backup_restore_log_status
          CHECK (status IN ('RUNNING', 'SUCCESS', 'ERROR'))

    , table_name               VARCHAR(60) NOT NULL

    , expected_row_count       INTEGER
      CONSTRAINT chk_tb_backup_restore_log_expected_row_count  CHECK (expected_row_count >= 0)

    , restored_row_count       INTEGER
      CONSTRAINT chk_tb_backup_restore_log_restored_row_count  CHECK (restored_row_count >= 0)

    , note                     TEXT
);
