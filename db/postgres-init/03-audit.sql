DROP TABLE IF EXISTS tb_log_address           CASCADE;
DROP TABLE IF EXISTS tb_log_habit             CASCADE;
DROP TABLE IF EXISTS tb_log_day_of_week       CASCADE;
DROP TABLE IF EXISTS tb_log_region            CASCADE;
DROP TABLE IF EXISTS tb_log_device            CASCADE;
DROP TABLE IF EXISTS tb_log_property          CASCADE;
DROP TABLE IF EXISTS tb_log_property_classification CASCADE;
DROP TABLE IF EXISTS tb_log_user              CASCADE;
DROP TABLE IF EXISTS tb_log_user_property     CASCADE;
DROP TABLE IF EXISTS tb_log_last_water_bill   CASCADE;
DROP TABLE IF EXISTS tb_log_user_habit_day    CASCADE;
DROP TABLE IF EXISTS tb_log_user_habit        CASCADE;
DROP TABLE IF EXISTS tb_log_region_rate       CASCADE;
DROP TABLE IF EXISTS tb_log_organization      CASCADE;
DROP TABLE IF EXISTS tb_log_user_organization  CASCADE;
DROP TABLE IF EXISTS tb_log_property_shift    CASCADE;
DROP TABLE IF EXISTS tb_log_water_usage_type  CASCADE;
DROP TABLE IF EXISTS tb_log_property_water_usage CASCADE;
DROP TABLE IF EXISTS tb_log_property_operation_day CASCADE;
DROP TABLE IF EXISTS tb_log_investment_scenario CASCADE;
DROP TABLE IF EXISTS tb_log_property_operational_profile CASCADE;

DROP TRIGGER IF EXISTS trg_log_region          ON tb_region;
DROP TRIGGER IF EXISTS trg_log_day_of_week     ON tb_day_of_week;
DROP TRIGGER IF EXISTS trg_log_habit           ON tb_habit;
DROP TRIGGER IF EXISTS trg_log_address         ON tb_address;
DROP TRIGGER IF EXISTS trg_log_user            ON tb_user;
DROP TRIGGER IF EXISTS trg_log_property        ON tb_property;
DROP TRIGGER IF EXISTS trg_log_property_classification ON tb_property_classification;
DROP TRIGGER IF EXISTS trg_log_user_property   ON tb_user_property;
DROP TRIGGER IF EXISTS trg_log_device          ON tb_device;
DROP TRIGGER IF EXISTS trg_log_region_rate     ON tb_region_rate;
DROP TRIGGER IF EXISTS trg_log_user_habit      ON tb_user_habit;
DROP TRIGGER IF EXISTS trg_log_user_habit_day  ON tb_user_habit_day;
DROP TRIGGER IF EXISTS trg_log_last_water_bill ON tb_last_water_bill;
DROP TRIGGER IF EXISTS trg_log_organization     ON tb_organization;
DROP TRIGGER IF EXISTS trg_log_user_organization ON tb_user_organization;
DROP TRIGGER IF EXISTS trg_log_property_shift   ON tb_property_shift;
DROP TRIGGER IF EXISTS trg_log_water_usage_type ON tb_water_usage_type;
DROP TRIGGER IF EXISTS trg_log_property_water_usage ON tb_property_water_usage;
DROP TRIGGER IF EXISTS trg_log_property_operation_day ON tb_property_operation_day;
DROP TRIGGER IF EXISTS trg_log_investment_scenario ON tb_investment_scenario;
DROP TRIGGER IF EXISTS trg_log_property_operational_profile ON tb_property_operational_profile;


CREATE TABLE tb_log_region (

      id                      SERIAL       PRIMARY KEY

    , region_id               INTEGER
    , name                    VARCHAR(30)

    , operation               VARCHAR(10)  NOT NULL
    , executed_by             VARCHAR(100) NOT NULL
    , executed_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
    , previous_log_id         INTEGER
    , log_description         TEXT

    , CONSTRAINT fk_tb_log_region_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_region (id)
);

CREATE OR REPLACE FUNCTION fn_log_region()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_region
        WHERE region_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_region
        WHERE region_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_region.';


        INSERT INTO tb_log_region
        (
              region_id
            , name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_region. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_region
        (
              region_id
            , name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_region.';


        INSERT INTO tb_log_region
        (
              region_id
            , name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_region
AFTER INSERT OR UPDATE OR DELETE
ON tb_region
FOR EACH ROW
EXECUTE FUNCTION fn_log_region();

CREATE TABLE tb_log_day_of_week (

      id                      SERIAL       PRIMARY KEY

    , day_of_week_id          INTEGER
    , name                    VARCHAR(20)

    , operation               VARCHAR(10)  NOT NULL
    , executed_by             VARCHAR(100) NOT NULL
    , executed_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
    , previous_log_id         INTEGER
    , log_description         TEXT

    , CONSTRAINT fk_tb_log_day_of_week_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_day_of_week (id)
);

CREATE OR REPLACE FUNCTION fn_log_day_of_week()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_day_of_week
        WHERE day_of_week_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_day_of_week
        WHERE day_of_week_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_day_of_week.';


        INSERT INTO tb_log_day_of_week
        (
              day_of_week_id
            , name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_day_of_week. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_day_of_week
        (
              day_of_week_id
            , name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_day_of_week.';


        INSERT INTO tb_log_day_of_week
        (
              day_of_week_id
            , name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_day_of_week
AFTER INSERT OR UPDATE OR DELETE
ON tb_day_of_week
FOR EACH ROW
EXECUTE FUNCTION fn_log_day_of_week();

CREATE TABLE tb_log_habit (

      id                      SERIAL       PRIMARY KEY

    , habit_id                INTEGER
    , name                    VARCHAR(30)
    , category                VARCHAR(30)
    , description             TEXT

    , operation               VARCHAR(10)  NOT NULL
    , executed_by             VARCHAR(100) NOT NULL
    , executed_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
    , previous_log_id         INTEGER
    , log_description         TEXT

    , CONSTRAINT fk_tb_log_habit_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_habit (id)
);


CREATE OR REPLACE FUNCTION fn_log_habit()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_habit
        WHERE habit_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_habit
        WHERE habit_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_habit.';


        INSERT INTO tb_log_habit
        (
              habit_id
            , name
            , category
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.name
            , NEW.category
            , NEW.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_habit. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_habit
        (
              habit_id
            , name
            , category
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.name
            , NEW.category
            , NEW.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_habit.';


        INSERT INTO tb_log_habit
        (
              habit_id
            , name
            , category
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.name
            , OLD.category
            , OLD.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_habit
AFTER INSERT OR UPDATE OR DELETE
ON tb_habit
FOR EACH ROW
EXECUTE FUNCTION fn_log_habit();

CREATE TABLE tb_log_address (

      id                      SERIAL       PRIMARY KEY

    , address_id              INTEGER
    , region_id               INTEGER
    , cep                     CHAR(8)
    , city                    VARCHAR(60)
    , state                   VARCHAR(30)
    , latitude                NUMERIC(8,6)
    , longitude               NUMERIC(9,6)

    , operation               VARCHAR(10)  NOT NULL
    , executed_by             VARCHAR(100) NOT NULL
    , executed_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
    , previous_log_id         INTEGER
    , log_description         TEXT

    , CONSTRAINT fk_tb_log_address_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_address (id)
);

CREATE OR REPLACE FUNCTION fn_log_address()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_address
        WHERE address_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_address
        WHERE address_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_address.';


        INSERT INTO tb_log_address
        (
              address_id
            , region_id
            , cep
            , city
            , state
            , latitude
            , longitude

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.region_id
            , NEW.cep
            , NEW.city
            , NEW.state
            , NEW.latitude
            , NEW.longitude

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_address. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_address
        (
              address_id
            , region_id
            , cep
            , city
            , state
            , latitude
            , longitude

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.region_id
            , NEW.cep
            , NEW.city
            , NEW.state
            , NEW.latitude
            , NEW.longitude

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_address.';


        INSERT INTO tb_log_address
        (
              address_id
            , region_id
            , cep
            , city
            , state
            , latitude
            , longitude

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.region_id
            , OLD.cep
            , OLD.city
            , OLD.state
            , OLD.latitude
            , OLD.longitude

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_address
AFTER INSERT OR UPDATE OR DELETE
ON tb_address
FOR EACH ROW
EXECUTE FUNCTION fn_log_address();

CREATE TABLE tb_log_user (

      id                    SERIAL PRIMARY KEY

    , user_id               INTEGER

    , name                  VARCHAR(100)
    , email                 VARCHAR(255)
    , phone                 VARCHAR(15)
    , birth_date            DATE
    , registration_date     DATE
    , is_active             BOOLEAN
    , is_admin              BOOLEAN
    , is_manager            BOOLEAN

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_user_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_user (id)

);

CREATE OR REPLACE FUNCTION fn_log_user()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_user
        WHERE user_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_user
        WHERE user_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_user.';


        INSERT INTO tb_log_user
        (
              user_id

            , name
            , email
            , phone
            , birth_date
            , registration_date
            , is_active
            , is_admin
            , is_manager

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.name
            , NEW.email
            , NEW.phone
            , NEW.birth_date
            , NEW.registration_date
            , NEW.is_active
            , NEW.is_admin
            , NEW.is_manager

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_user. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_user
        (
              user_id

            , name
            , email
            , phone
            , birth_date
            , registration_date
            , is_active
            , is_admin
            , is_manager

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.name
            , NEW.email
            , NEW.phone
            , NEW.birth_date
            , NEW.registration_date
            , NEW.is_active
            , NEW.is_admin
            , NEW.is_manager

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_user.';


        INSERT INTO tb_log_user
        (
              user_id

            , name
            , email
            , phone
            , birth_date
            , registration_date
            , is_active
            , is_admin
            , is_manager

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.name
            , OLD.email
            , OLD.phone
            , OLD.birth_date
            , OLD.registration_date
            , OLD.is_active
            , OLD.is_admin
            , OLD.is_manager

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_user
AFTER INSERT OR UPDATE OR DELETE
ON tb_user
FOR EACH ROW
EXECUTE FUNCTION fn_log_user();

CREATE TABLE tb_log_property (

      id                    SERIAL PRIMARY KEY

    , property_id           INTEGER

    , name                  VARCHAR(100)
    , type                  VARCHAR(20)
    , classification_id     INTEGER
    , address_id            INTEGER
    , registration_date     DATE

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_property_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_property (id)

);

CREATE OR REPLACE FUNCTION fn_log_property()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_property
        WHERE property_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_property
        WHERE property_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_property.';


        INSERT INTO tb_log_property
        (
              property_id

            , name
            , type
            , classification_id
            , address_id
            , registration_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.name
            , NEW.type
            , NEW.classification_id
            , NEW.address_id
            , NEW.registration_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_property. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_property
        (
              property_id

            , name
            , type
            , classification_id
            , address_id
            , registration_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.name
            , NEW.type
            , NEW.classification_id
            , NEW.address_id
            , NEW.registration_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_property.';


        INSERT INTO tb_log_property
        (
              property_id

            , name
            , type
            , classification_id
            , address_id
            , registration_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.name
            , OLD.type
            , OLD.classification_id
            , OLD.address_id
            , OLD.registration_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_property
AFTER INSERT OR UPDATE OR DELETE
ON tb_property
FOR EACH ROW
EXECUTE FUNCTION fn_log_property();

CREATE TABLE tb_log_property_classification (

      id                    SERIAL PRIMARY KEY

    , property_classification_id INTEGER
    , name                  VARCHAR(50)
    , group_name            VARCHAR(20)

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_property_classification_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_property_classification (id)

);

CREATE OR REPLACE FUNCTION fn_log_property_classification()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_classification
        WHERE property_classification_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_classification
        WHERE property_classification_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_property_classification.';


        INSERT INTO tb_log_property_classification
        (
              property_classification_id
            , name
            , group_name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.name
            , NEW.group_name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_property_classification. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_property_classification
        (
              property_classification_id
            , name
            , group_name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.name
            , NEW.group_name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_property_classification.';


        INSERT INTO tb_log_property_classification
        (
              property_classification_id
            , name
            , group_name

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.name
            , OLD.group_name

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_property_classification
AFTER INSERT OR UPDATE OR DELETE
ON tb_property_classification
FOR EACH ROW
EXECUTE FUNCTION fn_log_property_classification();

CREATE TABLE tb_log_user_property (

      id                    SERIAL PRIMARY KEY

    , user_property_id      INTEGER
    , user_id               INTEGER
    , property_id           INTEGER
    , association_date      DATE

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT

    , CONSTRAINT fk_tb_log_user_property_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_user_property (id)

);

CREATE OR REPLACE FUNCTION fn_log_user_property()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_user_property
        WHERE user_property_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_user_property
        WHERE user_property_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;

    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_user_property.';

        INSERT INTO tb_log_user_property
        (
              user_property_id
            , user_id
            , property_id
            , association_date
            , operation
            , executed_by
            , executed_at
            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.user_id
            , NEW.property_id
            , NEW.association_date
            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP
            , previous_log_id
            , log_description
        );

        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_user_property. Campos alterados:';

        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;

            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;

        INSERT INTO tb_log_user_property
        (
              user_property_id
            , user_id
            , property_id
            , association_date
            , operation
            , executed_by
            , executed_at
            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.user_id
            , NEW.property_id
            , NEW.association_date
            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP
            , previous_log_id
            , log_description
        );

        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_user_property.';

        INSERT INTO tb_log_user_property
        (
              user_property_id
            , user_id
            , property_id
            , association_date
            , operation
            , executed_by
            , executed_at
            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.user_id
            , OLD.property_id
            , OLD.association_date
            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP
            , previous_log_id
            , log_description
        );

        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_user_property
AFTER INSERT OR UPDATE OR DELETE
ON tb_user_property
FOR EACH ROW
EXECUTE FUNCTION fn_log_user_property();

CREATE TABLE tb_log_device (

      id                    SERIAL PRIMARY KEY

    , device_id_log         INTEGER
    , device_id             VARCHAR(100)
    , property_id           INTEGER
    , is_active             BOOLEAN
    , installation_date     DATE

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    
    , CONSTRAINT fk_tb_log_device_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_device (id)
);

CREATE OR REPLACE FUNCTION fn_log_device()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_device
        WHERE device_id_log = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_device
        WHERE device_id_log = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;

    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_device.';

        INSERT INTO tb_log_device
        (
              device_id_log
            , device_id
            , property_id
            , is_active
            , installation_date
            , operation
            , executed_by
            , executed_at
            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.device_id
            , NEW.property_id
            , NEW.is_active
            , NEW.installation_date
            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP
            , previous_log_id
            , log_description
        );

        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_device. Campos alterados:';

        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;

            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;

        INSERT INTO tb_log_device
        (
              device_id_log
            , device_id
            , property_id
            , is_active
            , installation_date
            , operation
            , executed_by
            , executed_at
            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.device_id
            , NEW.property_id
            , NEW.is_active
            , NEW.installation_date
            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP
            , previous_log_id
            , log_description
        );

        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_device.';

        INSERT INTO tb_log_device
        (
              device_id_log
            , device_id
            , property_id
            , is_active
            , installation_date
            , operation
            , executed_by
            , executed_at
            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.device_id
            , OLD.property_id
            , OLD.is_active
            , OLD.installation_date
            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP
            , previous_log_id
            , log_description
        );

        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_device
AFTER INSERT OR UPDATE OR DELETE
ON tb_device
FOR EACH ROW
EXECUTE FUNCTION fn_log_device();

CREATE TABLE tb_log_region_rate (

      id                    SERIAL PRIMARY KEY

    , region_rate_id        INTEGER
    , region_id             INTEGER
    , classification_id     INTEGER
    , m3_value              NUMERIC(10,2)
    , initial_validity      DATE
    , final_validity        DATE

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT

    , CONSTRAINT fk_tb_log_region_rate_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_region_rate (id)

);

CREATE OR REPLACE FUNCTION fn_log_region_rate()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_region_rate
        WHERE region_rate_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_region_rate
        WHERE region_rate_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_region_rate.';


        INSERT INTO tb_log_region_rate
        (
              region_rate_id
            , region_id
            , classification_id
            , m3_value
            , initial_validity
            , final_validity

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.region_id
            , NEW.classification_id
            , NEW.m3_value
            , NEW.initial_validity
            , NEW.final_validity

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_region_rate. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_region_rate
        (
              region_rate_id
            , region_id
            , classification_id
            , m3_value
            , initial_validity
            , final_validity

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.region_id
            , NEW.classification_id
            , NEW.m3_value
            , NEW.initial_validity
            , NEW.final_validity

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_region_rate.';


        INSERT INTO tb_log_region_rate
        (
              region_rate_id
            , region_id
            , classification_id
            , m3_value
            , initial_validity
            , final_validity

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.region_id
            , OLD.classification_id
            , OLD.m3_value
            , OLD.initial_validity
            , OLD.final_validity

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_region_rate
AFTER INSERT OR UPDATE OR DELETE
ON tb_region_rate
FOR EACH ROW
EXECUTE FUNCTION fn_log_region_rate();

CREATE TABLE tb_log_user_habit (

      id                    SERIAL PRIMARY KEY

    , user_habit_id         INTEGER
    , user_id               INTEGER
    , habit_id              INTEGER
    , frequency             INTEGER
    , start_time            TIME
    , end_time              TIME
    , estimated_liters      NUMERIC(6, 2)

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT

    , CONSTRAINT fk_tb_log_user_habit_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_user_habit (id)

);

CREATE OR REPLACE FUNCTION fn_log_user_habit()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_user_habit
        WHERE user_habit_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_user_habit
        WHERE user_habit_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_user_habit.';


        INSERT INTO tb_log_user_habit
        (
              user_habit_id
            , user_id
            , habit_id
            , frequency
            , start_time
            , end_time
            , estimated_liters

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.user_id
            , NEW.habit_id
            , NEW.frequency
            , NEW.start_time
            , NEW.end_time
            , NEW.estimated_liters

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_user_habit. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_user_habit
        (
              user_habit_id
            , user_id
            , habit_id
            , frequency
            , start_time
            , end_time
            , estimated_liters

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.user_id
            , NEW.habit_id
            , NEW.frequency
            , NEW.start_time
            , NEW.end_time
            , NEW.estimated_liters

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_user_habit.';


        INSERT INTO tb_log_user_habit
        (
              user_habit_id
            , user_id
            , habit_id
            , frequency
            , start_time
            , end_time
            , estimated_liters

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.user_id
            , OLD.habit_id
            , OLD.frequency
            , OLD.start_time
            , OLD.end_time
            , OLD.estimated_liters

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_user_habit
AFTER INSERT OR UPDATE OR DELETE
ON tb_user_habit
FOR EACH ROW
EXECUTE FUNCTION fn_log_user_habit();

CREATE TABLE tb_log_user_habit_day (

      id                    SERIAL PRIMARY KEY

    , user_habit_day_id     INTEGER
    , user_habit_id         INTEGER
    , day_of_week_id        INTEGER

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT

    , CONSTRAINT fk_tb_log_user_habit_day_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_user_habit_day (id)

);

CREATE OR REPLACE FUNCTION fn_log_user_habit_day()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_user_habit_day
        WHERE user_habit_day_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_user_habit_day
        WHERE user_habit_day_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_user_habit_day.';


        INSERT INTO tb_log_user_habit_day
        (
              user_habit_day_id
            , user_habit_id
            , day_of_week_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.user_habit_id
            , NEW.day_of_week_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_user_habit_day. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_user_habit_day
        (
              user_habit_day_id
            , user_habit_id
            , day_of_week_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.user_habit_id
            , NEW.day_of_week_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_user_habit_day.';


        INSERT INTO tb_log_user_habit_day
        (
              user_habit_day_id
            , user_habit_id
            , day_of_week_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.user_habit_id
            , OLD.day_of_week_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_user_habit_day
AFTER INSERT OR UPDATE OR DELETE
ON tb_user_habit_day
FOR EACH ROW
EXECUTE FUNCTION fn_log_user_habit_day();

CREATE TABLE tb_log_last_water_bill (

      id                    SERIAL PRIMARY KEY

    , last_water_bill_id    INTEGER
    , user_id               INTEGER
    , month                 DATE
    , total_value           NUMERIC(10,2)
    , m3_value              NUMERIC(10,2)

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_last_water_bill_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_last_water_bill (id)

);

CREATE OR REPLACE FUNCTION fn_log_last_water_bill()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_last_water_bill
        WHERE last_water_bill_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_last_water_bill
        WHERE last_water_bill_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_last_water_bill.';


        INSERT INTO tb_log_last_water_bill
        (
              last_water_bill_id
            , user_id
            , month
            , total_value
            , m3_value

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.user_id
            , NEW.month
            , NEW.total_value
            , NEW.m3_value

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_last_water_bill. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_last_water_bill
        (
              last_water_bill_id
            , user_id
            , month
            , total_value
            , m3_value

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id
            , NEW.user_id
            , NEW.month
            , NEW.total_value
            , NEW.m3_value

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_last_water_bill.';


        INSERT INTO tb_log_last_water_bill
        (
              last_water_bill_id
            , user_id
            , month
            , total_value
            , m3_value

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id
            , OLD.user_id
            , OLD.month
            , OLD.total_value
            , OLD.m3_value

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_last_water_bill
AFTER INSERT OR UPDATE OR DELETE
ON tb_last_water_bill
FOR EACH ROW
EXECUTE FUNCTION fn_log_last_water_bill();
CREATE TABLE tb_log_organization (

      id                    SERIAL PRIMARY KEY

    , organization_id       INTEGER

    , corporate_name        VARCHAR(150)
    , trade_name            VARCHAR(150)
    , cnpj                  CHAR(14)
    , business_segment      VARCHAR(20)
    , declared_unit_count   INTEGER
    , registration_date     DATE

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_organization_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_organization (id)

);

CREATE OR REPLACE FUNCTION fn_log_organization()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_organization
        WHERE organization_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_organization
        WHERE organization_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_organization.';


        INSERT INTO tb_log_organization
        (
              organization_id

            , corporate_name
            , trade_name
            , cnpj
            , business_segment
            , declared_unit_count
            , registration_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.corporate_name
            , NEW.trade_name
            , NEW.cnpj
            , NEW.business_segment
            , NEW.declared_unit_count
            , NEW.registration_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_organization. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_organization
        (
              organization_id

            , corporate_name
            , trade_name
            , cnpj
            , business_segment
            , declared_unit_count
            , registration_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.corporate_name
            , NEW.trade_name
            , NEW.cnpj
            , NEW.business_segment
            , NEW.declared_unit_count
            , NEW.registration_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_organization.';


        INSERT INTO tb_log_organization
        (
              organization_id

            , corporate_name
            , trade_name
            , cnpj
            , business_segment
            , declared_unit_count
            , registration_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.corporate_name
            , OLD.trade_name
            , OLD.cnpj
            , OLD.business_segment
            , OLD.declared_unit_count
            , OLD.registration_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_organization
AFTER INSERT OR UPDATE OR DELETE
ON tb_organization
FOR EACH ROW
EXECUTE FUNCTION fn_log_organization();

CREATE TABLE tb_log_user_organization (

      id                    SERIAL PRIMARY KEY

    , user_organization_id  INTEGER

    , user_id               INTEGER
    , organization_id       INTEGER
    , association_date      DATE

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_user_organization_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_user_organization (id)

);

CREATE OR REPLACE FUNCTION fn_log_user_organization()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_user_organization
        WHERE user_organization_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_user_organization
        WHERE user_organization_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_user_organization.';


        INSERT INTO tb_log_user_organization
        (
              user_organization_id

            , user_id
            , organization_id
            , association_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.user_id
            , NEW.organization_id
            , NEW.association_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_user_organization. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_user_organization
        (
              user_organization_id

            , user_id
            , organization_id
            , association_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.user_id
            , NEW.organization_id
            , NEW.association_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_user_organization.';


        INSERT INTO tb_log_user_organization
        (
              user_organization_id

            , user_id
            , organization_id
            , association_date

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.user_id
            , OLD.organization_id
            , OLD.association_date

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_user_organization
AFTER INSERT OR UPDATE OR DELETE
ON tb_user_organization
FOR EACH ROW
EXECUTE FUNCTION fn_log_user_organization();

CREATE TABLE tb_log_property_shift (

      id                    SERIAL PRIMARY KEY

    , property_shift_id     INTEGER

    , property_id           INTEGER
    , start_time            TIME
    , end_time              TIME

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_property_shift_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_property_shift (id)

);

CREATE OR REPLACE FUNCTION fn_log_property_shift()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_shift
        WHERE property_shift_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_shift
        WHERE property_shift_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_property_shift.';


        INSERT INTO tb_log_property_shift
        (
              property_shift_id

            , property_id
            , start_time
            , end_time

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.property_id
            , NEW.start_time
            , NEW.end_time

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_property_shift. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_property_shift
        (
              property_shift_id

            , property_id
            , start_time
            , end_time

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.property_id
            , NEW.start_time
            , NEW.end_time

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_property_shift.';


        INSERT INTO tb_log_property_shift
        (
              property_shift_id

            , property_id
            , start_time
            , end_time

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.property_id
            , OLD.start_time
            , OLD.end_time

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_property_shift
AFTER INSERT OR UPDATE OR DELETE
ON tb_property_shift
FOR EACH ROW
EXECUTE FUNCTION fn_log_property_shift();

CREATE TABLE tb_log_water_usage_type (

      id                    SERIAL PRIMARY KEY

    , water_usage_type_id   INTEGER

    , name                  VARCHAR(30)
    , description           TEXT

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_water_usage_type_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_water_usage_type (id)

);

CREATE OR REPLACE FUNCTION fn_log_water_usage_type()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_water_usage_type
        WHERE water_usage_type_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_water_usage_type
        WHERE water_usage_type_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_water_usage_type.';


        INSERT INTO tb_log_water_usage_type
        (
              water_usage_type_id

            , name
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.name
            , NEW.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_water_usage_type. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_water_usage_type
        (
              water_usage_type_id

            , name
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.name
            , NEW.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_water_usage_type.';


        INSERT INTO tb_log_water_usage_type
        (
              water_usage_type_id

            , name
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.name
            , OLD.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_water_usage_type
AFTER INSERT OR UPDATE OR DELETE
ON tb_water_usage_type
FOR EACH ROW
EXECUTE FUNCTION fn_log_water_usage_type();

CREATE TABLE tb_log_property_water_usage (

      id                    SERIAL PRIMARY KEY

    , property_water_usage_id INTEGER

    , property_id           INTEGER
    , water_usage_type_id   INTEGER

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_property_water_usage_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_property_water_usage (id)

);

CREATE OR REPLACE FUNCTION fn_log_property_water_usage()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_water_usage
        WHERE property_water_usage_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_water_usage
        WHERE property_water_usage_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_property_water_usage.';


        INSERT INTO tb_log_property_water_usage
        (
              property_water_usage_id

            , property_id
            , water_usage_type_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.property_id
            , NEW.water_usage_type_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_property_water_usage. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_property_water_usage
        (
              property_water_usage_id

            , property_id
            , water_usage_type_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.property_id
            , NEW.water_usage_type_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_property_water_usage.';


        INSERT INTO tb_log_property_water_usage
        (
              property_water_usage_id

            , property_id
            , water_usage_type_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.property_id
            , OLD.water_usage_type_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_property_water_usage
AFTER INSERT OR UPDATE OR DELETE
ON tb_property_water_usage
FOR EACH ROW
EXECUTE FUNCTION fn_log_property_water_usage();

CREATE TABLE tb_log_property_operation_day (

      id                    SERIAL PRIMARY KEY

    , property_operation_day_id INTEGER

    , property_id           INTEGER
    , day_of_week_id        INTEGER

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_property_operation_day_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_property_operation_day (id)

);

CREATE OR REPLACE FUNCTION fn_log_property_operation_day()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_operation_day
        WHERE property_operation_day_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_operation_day
        WHERE property_operation_day_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_property_operation_day.';


        INSERT INTO tb_log_property_operation_day
        (
              property_operation_day_id

            , property_id
            , day_of_week_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.property_id
            , NEW.day_of_week_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_property_operation_day. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_property_operation_day
        (
              property_operation_day_id

            , property_id
            , day_of_week_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.property_id
            , NEW.day_of_week_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_property_operation_day.';


        INSERT INTO tb_log_property_operation_day
        (
              property_operation_day_id

            , property_id
            , day_of_week_id

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.property_id
            , OLD.day_of_week_id

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_property_operation_day
AFTER INSERT OR UPDATE OR DELETE
ON tb_property_operation_day
FOR EACH ROW
EXECUTE FUNCTION fn_log_property_operation_day();

CREATE TABLE tb_log_investment_scenario (

      id                    SERIAL PRIMARY KEY

    , investment_scenario_id INTEGER

    , organization_id       INTEGER
    , name                  VARCHAR(100)
    , investment_value      NUMERIC(10,2)
    , reduction_pct         NUMERIC(5,2)
    , annual_savings_value  NUMERIC(10,2)
    , payback_months        NUMERIC(6,1)
    , description           TEXT

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_investment_scenario_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_investment_scenario (id)

);

CREATE OR REPLACE FUNCTION fn_log_investment_scenario()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_investment_scenario
        WHERE investment_scenario_id = NEW.id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_investment_scenario
        WHERE investment_scenario_id = OLD.id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_investment_scenario.';


        INSERT INTO tb_log_investment_scenario
        (
              investment_scenario_id

            , organization_id
            , name
            , investment_value
            , reduction_pct
            , annual_savings_value
            , payback_months
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.organization_id
            , NEW.name
            , NEW.investment_value
            , NEW.reduction_pct
            , NEW.annual_savings_value
            , NEW.payback_months
            , NEW.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_investment_scenario. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_investment_scenario
        (
              investment_scenario_id

            , organization_id
            , name
            , investment_value
            , reduction_pct
            , annual_savings_value
            , payback_months
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.id

            , NEW.organization_id
            , NEW.name
            , NEW.investment_value
            , NEW.reduction_pct
            , NEW.annual_savings_value
            , NEW.payback_months
            , NEW.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_investment_scenario.';


        INSERT INTO tb_log_investment_scenario
        (
              investment_scenario_id

            , organization_id
            , name
            , investment_value
            , reduction_pct
            , annual_savings_value
            , payback_months
            , description

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.id

            , OLD.organization_id
            , OLD.name
            , OLD.investment_value
            , OLD.reduction_pct
            , OLD.annual_savings_value
            , OLD.payback_months
            , OLD.description

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_investment_scenario
AFTER INSERT OR UPDATE OR DELETE
ON tb_investment_scenario
FOR EACH ROW
EXECUTE FUNCTION fn_log_investment_scenario();

CREATE TABLE tb_log_property_operational_profile (

      id                    SERIAL PRIMARY KEY

    , property_operational_profile_id INTEGER

    , main_water_source     VARCHAR(20)

    , operation             VARCHAR(10) NOT NULL
    , executed_by           VARCHAR(100) NOT NULL
    , executed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

    , previous_log_id       INTEGER
    , log_description       TEXT
    , CONSTRAINT fk_tb_log_property_operational_profile_previous_log
        FOREIGN KEY (previous_log_id)
        REFERENCES tb_log_property_operational_profile (id)

);

CREATE OR REPLACE FUNCTION fn_log_property_operational_profile()

RETURNS TRIGGER

LANGUAGE plpgsql

AS $$

DECLARE

    field_name         TEXT;
    old_value          TEXT;
    new_value          TEXT;

    previous_log_id    INTEGER;

    log_description    TEXT;

BEGIN

    IF TG_OP <> 'DELETE' THEN

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_operational_profile
        WHERE property_operational_profile_id = NEW.property_id
        ORDER BY id DESC
        LIMIT 1;

    ELSE

        SELECT id
        INTO previous_log_id
        FROM tb_log_property_operational_profile
        WHERE property_operational_profile_id = OLD.property_id
        ORDER BY id DESC
        LIMIT 1;

    END IF;


    IF TG_OP = 'INSERT' THEN

        log_description :=
            'Registro inserido na tabela tb_property_operational_profile.';


        INSERT INTO tb_log_property_operational_profile
        (
              property_operational_profile_id

            , main_water_source

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.property_id

            , NEW.main_water_source

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'UPDATE' THEN

        log_description :=
            'Registro atualizado na tabela tb_property_operational_profile. Campos alterados:';


        FOR field_name, old_value IN

            SELECT *
            FROM json_each_text(row_to_json(OLD))

        LOOP

            new_value := row_to_json(NEW) ->> field_name;


            IF old_value IS DISTINCT FROM new_value THEN

                log_description :=
                    log_description ||
                    E'\n- Campo: ' ||
                    field_name ||
                    ' | Valor antigo: "' ||
                    COALESCE(old_value, '<NULL>') ||
                    '" | Valor novo: "' ||
                    COALESCE(new_value, '<NULL>') ||
                    '"';

            END IF;

        END LOOP;


        INSERT INTO tb_log_property_operational_profile
        (
              property_operational_profile_id

            , main_water_source

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              NEW.property_id

            , NEW.main_water_source

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN NEW;


    ELSIF TG_OP = 'DELETE' THEN

        log_description :=
            'Registro removido da tabela tb_property_operational_profile.';


        INSERT INTO tb_log_property_operational_profile
        (
              property_operational_profile_id

            , main_water_source

            , operation
            , executed_by
            , executed_at

            , previous_log_id
            , log_description
        )

        VALUES
        (
              OLD.property_id

            , OLD.main_water_source

            , TG_OP
            , CURRENT_USER
            , CURRENT_TIMESTAMP

            , previous_log_id
            , log_description
        );


        RETURN OLD;

    END IF;

END;

$$;

CREATE TRIGGER trg_log_property_operational_profile
AFTER INSERT OR UPDATE OR DELETE
ON tb_property_operational_profile
FOR EACH ROW
EXECUTE FUNCTION fn_log_property_operational_profile();

