CREATE OR REPLACE FUNCTION fn_get_current_region_rate(
    p_region_id INTEGER,
    p_classification_id INTEGER,
    p_date DATE
)
RETURNS NUMERIC(10,2)
LANGUAGE plpgsql
AS $$
DECLARE
    v_m3_value NUMERIC(10,2);
BEGIN

    SELECT m3_value
      INTO v_m3_value
      FROM tb_region_rate
     WHERE region_id = p_region_id
       AND classification_id = p_classification_id
       AND initial_validity <= p_date
       AND (
            final_validity IS NULL
            OR final_validity >= p_date
       )
     ORDER BY initial_validity DESC
     LIMIT 1;


    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Não existe tarifa válida para a região %, categoria % na data %.',
            p_region_id,
            p_classification_id,
            p_date;
    END IF;


    RETURN v_m3_value;

END;
$$;
CREATE OR REPLACE FUNCTION fn_get_dau(
    p_date DATE
)
RETURNS INTEGER
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_dau INTEGER;
BEGIN

    IF p_date IS NULL THEN
        RAISE EXCEPTION 'A data não pode ser nula.';
    END IF;

    SELECT COUNT(DISTINCT user_id)
    INTO v_dau
    FROM tb_user_access_log
    WHERE accessed_at::DATE = p_date;

    RETURN v_dau;

END;
$$;

CREATE OR REPLACE FUNCTION fn_get_property_classification(
    p_property_id INTEGER
)
RETURNS VARCHAR(50)
LANGUAGE plpgsql
AS $$
DECLARE
    v_classification VARCHAR(50);
BEGIN

    SELECT pc.name
      INTO v_classification
      FROM tb_property p
      JOIN tb_property_classification pc
        ON pc.id = p.classification_id
     WHERE p.id = p_property_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Imóvel com id % não encontrado.',
            p_property_id;
    END IF;

    RETURN v_classification;

END;
$$;

CREATE OR REPLACE FUNCTION fn_get_property_classification_group(
    p_property_id INTEGER
)
RETURNS VARCHAR(20)
LANGUAGE plpgsql
AS $$
DECLARE
    v_group_name VARCHAR(20);
BEGIN

    SELECT pc.group_name
      INTO v_group_name
      FROM tb_property p
      JOIN tb_property_classification pc
        ON pc.id = p.classification_id
     WHERE p.id = p_property_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Imóvel com id % não encontrado.',
            p_property_id;
    END IF;

    RETURN v_group_name;

END;
$$;

CREATE OR REPLACE FUNCTION fn_get_property_region(
    p_property_id INTEGER
)
RETURNS VARCHAR(30)
LANGUAGE plpgsql
AS $$
DECLARE
    v_region_name VARCHAR(30);
BEGIN

    SELECT r.name
      INTO v_region_name
      FROM tb_property p
      JOIN tb_address a
        ON a.id = p.address_id
      JOIN tb_region r
        ON r.id = a.region_id
     WHERE p.id = p_property_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Imóvel com id % não encontrado.',
            p_property_id;
    END IF;

    RETURN v_region_name;

END;
$$;
CREATE OR REPLACE FUNCTION fn_user_can_estimate(
    p_user_id INTEGER
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_property_id INTEGER;
    v_region_id INTEGER;
    v_classification_id INTEGER;
BEGIN

    -- Verifica se o usuário existe e está ativo
    IF NOT fn_user_is_active(p_user_id) THEN
        RETURN FALSE;
    END IF;


    -- Busca uma propriedade vinculada ao usuário
    SELECT property_id
      INTO v_property_id
      FROM tb_user_property
     WHERE user_id = p_user_id
     LIMIT 1;


    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;


    -- Verifica se existe dispositivo ativo na propriedade
    IF NOT EXISTS
    (
        SELECT 1
          FROM tb_device
         WHERE property_id = v_property_id
           AND is_active = TRUE
    )
    THEN
        RETURN FALSE;
    END IF;


    -- Busca a região e a categoria da propriedade
    SELECT a.region_id, p.classification_id
      INTO v_region_id, v_classification_id
      FROM tb_address a
      JOIN tb_property p
        ON p.address_id = a.id
     WHERE p.id = v_property_id;


    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;


    -- Verifica se existe tarifa cadastrada para a região e categoria
    IF NOT EXISTS
    (
        SELECT 1
          FROM tb_region_rate
         WHERE region_id = v_region_id
           AND classification_id = v_classification_id
           AND initial_validity <= CURRENT_DATE
           AND (
                final_validity IS NULL
                OR final_validity >= CURRENT_DATE
           )
    )
    THEN
        RETURN FALSE;
    END IF;


    RETURN TRUE;

END;
$$;


CREATE OR REPLACE FUNCTION fn_user_is_active(
    p_user_id INTEGER
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_is_active BOOLEAN;
BEGIN
    SELECT is_active
    INTO v_is_active
    FROM tb_user
    WHERE id = p_user_id;

    IF NOT FOUND THEN 
        RAISE EXCEPTION 'Usuário com id % não encontrado.', p_user_id;
    END IF;

    RETURN v_is_active;

END;
$$;
CREATE OR REPLACE PROCEDURE sp_change_region_rate(
    p_region_id INTEGER,
    p_classification_id INTEGER,
    p_new_rate NUMERIC(10,2),
    p_initial_validity DATE
)
LANGUAGE plpgsql
AS $$
BEGIN

    -- Verifica se a região existe
    IF NOT EXISTS
    (
        SELECT 1
          FROM tb_region
         WHERE id = p_region_id
    )
    THEN
        RAISE EXCEPTION
            'Região com id % não encontrada.',
            p_region_id;
    END IF;


    -- Verifica se a categoria existe
    IF NOT EXISTS
    (
        SELECT 1
          FROM tb_property_classification
         WHERE id = p_classification_id
    )
    THEN
        RAISE EXCEPTION
            'Categoria com id % não encontrada.',
            p_classification_id;
    END IF;


    -- Valida o valor da tarifa
    IF p_new_rate <= 0 THEN
        RAISE EXCEPTION
            'O valor da tarifa deve ser maior que zero.';
    END IF;


    -- Fecha a tarifa atualmente vigente
    UPDATE tb_region_rate
       SET final_validity = p_initial_validity - INTERVAL '1 day'
     WHERE region_id = p_region_id
       AND classification_id = p_classification_id
       AND final_validity IS NULL;


    -- Insere a nova tarifa
    INSERT INTO tb_region_rate
    (
        region_id,
        classification_id,
        m3_value,
        initial_validity,
        final_validity
    )
    VALUES
    (
        p_region_id,
        p_classification_id,
        p_new_rate,
        p_initial_validity,
        NULL
    );


END;
$$;
CREATE OR REPLACE PROCEDURE sp_disable_user(
    p_user_id INTEGER
)
LANGUAGE plpgsql
AS $$
BEGIN


    -- Verifica se o usuário existe
    IF NOT EXISTS
    (
        SELECT 1
          FROM tb_user
         WHERE id = p_user_id
    )
    THEN

        RAISE EXCEPTION
            'Usuário % não encontrado.',
            p_user_id;

    END IF;



    -- Desativa o usuário
    UPDATE tb_user
       SET is_active = FALSE
     WHERE id = p_user_id;



    -- Desativa dispositivos das propriedades do usuário
    UPDATE tb_device
       SET is_active = FALSE
     WHERE property_id IN
     (
        SELECT property_id
          FROM tb_user_property
         WHERE user_id = p_user_id
     );


END;
$$;
CREATE OR REPLACE PROCEDURE sp_register_property(
    IN p_user_id INTEGER,
    IN p_name VARCHAR(100),
    IN p_type VARCHAR(20),
    IN p_classification VARCHAR(50),
    IN p_address_id INTEGER,
    IN p_organization_id INTEGER,
    IN p_built_area_m2 NUMERIC(10,2),
    OUT v_property_id INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_classification_id INTEGER;
BEGIN


    -- Verifica se o usuário existe e está ativo
    IF NOT fn_user_is_active(p_user_id) THEN

        RAISE EXCEPTION
            'Usuário % inexistente ou inativo.',
            p_user_id;

    END IF;



    -- Verifica se o endereço existe
    IF NOT EXISTS
    (
        SELECT 1
          FROM tb_address
         WHERE id = p_address_id
    )
    THEN

        RAISE EXCEPTION
            'Endereço % não encontrado.',
            p_address_id;

    END IF;



    -- Resolve o nome da classificação pro id correspondente
    SELECT id
      INTO v_classification_id
      FROM tb_property_classification
     WHERE name = p_classification;

    IF NOT FOUND THEN

        RAISE EXCEPTION
            'Classificação % não encontrada.',
            p_classification;

    END IF;



    -- Verifica se a organização existe, quando informada (imóvel comercial/industrial)
    IF p_organization_id IS NOT NULL AND NOT EXISTS
    (
        SELECT 1
          FROM tb_organization
         WHERE id = p_organization_id
    )
    THEN

        RAISE EXCEPTION
            'Organização % não encontrada.',
            p_organization_id;

    END IF;



    -- Insere a propriedade
    INSERT INTO tb_property
    (
        name,
        type,
        classification_id,
        address_id,
        organization_id,
        built_area_m2
    )
    VALUES
    (
        p_name,
        p_type,
        v_classification_id,
        p_address_id,
        p_organization_id,
        p_built_area_m2
    )
    RETURNING id INTO v_property_id;



    -- Cria vínculo entre usuário e propriedade
    INSERT INTO tb_user_property
    (
        user_id,
        property_id
    )
    VALUES
    (
        p_user_id,
        v_property_id
    );


END;
$$;

CREATE OR REPLACE PROCEDURE sp_register_user_access(
    p_user_id INTEGER,
    p_access_channel VARCHAR(20) DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN

    -- fn_user_is_active já lança exceção se o usuário não existir
    IF NOT fn_user_is_active(p_user_id) THEN
        RAISE EXCEPTION 'Usuário % está inativo e não pode ter acesso registrado.', p_user_id;
    END IF;

    INSERT INTO tb_user_access_log (user_id, access_channel)
    VALUES (p_user_id, p_access_channel);

END;
$$;

CREATE OR REPLACE PROCEDURE sp_update_property_classification(
    p_property_id INTEGER,
    p_classification VARCHAR(50)
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_classification_id INTEGER;
BEGIN


    -- Verifica se o imóvel existe
    IF NOT EXISTS
    (
        SELECT 1
          FROM tb_property
         WHERE id = p_property_id
    )
    THEN

        RAISE EXCEPTION
            'Imóvel % não encontrado.',
            p_property_id;

    END IF;



    -- Resolve o nome da classificação pro id correspondente
    SELECT id
      INTO v_classification_id
      FROM tb_property_classification
     WHERE name = p_classification;

    IF NOT FOUND THEN

        RAISE EXCEPTION
            'Classificação % não encontrada.',
            p_classification;

    END IF;



    -- Atualiza a classificação (o trigger trg_log_property audita a mudança)
    UPDATE tb_property
       SET classification_id = v_classification_id
     WHERE id = p_property_id;

    IF NOT FOUND THEN

        RAISE EXCEPTION
            'Imóvel % não encontrado.',
            p_property_id;

    END IF;


END;
$$;

CREATE OR REPLACE FUNCTION fn_user_access_kind(
    p_user_id INTEGER
)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
BEGIN

    IF EXISTS
    (
        SELECT 1
          FROM tb_user_property
         WHERE user_id = p_user_id
    )
    THEN
        RETURN 'residential';
    END IF;


    IF EXISTS
    (
        SELECT 1
          FROM tb_user_organization
         WHERE user_id = p_user_id
    )
    THEN
        RETURN 'organizational';
    END IF;


    RETURN 'none';

END;
$$;

CREATE OR REPLACE FUNCTION fn_user_organization_properties(
    p_user_id INTEGER
)
RETURNS TABLE (
    property_id INTEGER,
    name        VARCHAR,
    city        VARCHAR,
    state       VARCHAR
)
LANGUAGE plpgsql
AS $$
BEGIN

    RETURN QUERY
    SELECT
          p.id
        , p.name
        , a.city
        , a.state
      FROM tb_user_organization uo
      JOIN tb_property p
        ON p.organization_id = uo.organization_id
      JOIN tb_address a
        ON a.id = p.address_id
     WHERE uo.user_id = p_user_id;

END;
$$;

CREATE OR REPLACE FUNCTION fn_user_authorized_property_ids(
    p_user_id      INTEGER,
    p_property_ids INTEGER[]
)
RETURNS INTEGER[]
LANGUAGE plpgsql
AS $$
DECLARE
    v_authorized INTEGER[];
BEGIN

    SELECT COALESCE(ARRAY_AGG(p.id), ARRAY[]::INTEGER[])
      INTO v_authorized
      FROM tb_user_organization uo
      JOIN tb_property p
        ON p.organization_id = uo.organization_id
     WHERE uo.user_id = p_user_id
       AND p.id = ANY(p_property_ids);

    RETURN v_authorized;

END;
$$;

DROP FUNCTION IF EXISTS fn_organization_can_estimate(INTEGER[]);

CREATE OR REPLACE FUNCTION fn_organization_can_estimate(
    p_user_id      INTEGER,
    p_property_ids INTEGER[]
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_property_ids INTEGER[] := fn_user_authorized_property_ids(p_user_id, p_property_ids);
BEGIN

    RETURN EXISTS
    (
        SELECT 1
          FROM gold.ft_consumption_daily f
          JOIN gold.dm_property dp
            ON dp.property_key = f.property_key
         WHERE dp.property_id = ANY(v_property_ids)
    );

END;
$$;

DROP FUNCTION IF EXISTS fn_organization_consumption_history(INTEGER[], INTEGER, DATE);

CREATE OR REPLACE FUNCTION fn_organization_consumption_history(
    p_user_id      INTEGER,
    p_property_ids INTEGER[],
    p_days         INTEGER,
    p_today        DATE
)
RETURNS TABLE (
    full_date    DATE,
    total_liters NUMERIC
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_property_ids INTEGER[] := fn_user_authorized_property_ids(p_user_id, p_property_ids);
BEGIN

    RETURN QUERY
    SELECT
          v.full_date
        , SUM(v.total_liters) AS total_liters
      FROM dw.vw_ft_consumption_daily v
     WHERE v.property_id = ANY(v_property_ids)
       AND v.full_date BETWEEN (p_today - (p_days - 1)) AND p_today
     GROUP BY v.full_date
     ORDER BY v.full_date;

END;
$$;

DROP FUNCTION IF EXISTS fn_organization_last_billed_period(INTEGER[], DATE);

CREATE OR REPLACE FUNCTION fn_organization_last_billed_period(
    p_user_id      INTEGER,
    p_property_ids INTEGER[],
    p_today        DATE
)
RETURNS TABLE (
    reference_month DATE,
    total_liters    NUMERIC,
    total_cost      NUMERIC
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_property_ids INTEGER[] := fn_user_authorized_property_ids(p_user_id, p_property_ids);
    v_last_closed_month DATE := DATE_TRUNC('month', p_today) - INTERVAL '1 month';
BEGIN

    RETURN QUERY
    SELECT
          v_last_closed_month
        , SUM(v.total_liters)
        , SUM(v.cost_value)
      FROM dw.vw_ft_consumption_daily v
     WHERE v.property_id = ANY(v_property_ids)
       AND DATE_TRUNC('month', v.full_date) = v_last_closed_month
    HAVING SUM(v.total_liters) IS NOT NULL;

    IF FOUND THEN
        RETURN;
    END IF;


    RETURN QUERY
    SELECT
          DATE_TRUNC('month', MAX(v.full_date))::DATE
        , SUM(v.total_liters)
        , SUM(v.cost_value)
      FROM dw.vw_ft_consumption_daily v
     WHERE v.property_id = ANY(v_property_ids)
    HAVING SUM(v.total_liters) IS NOT NULL;

END;
$$;

DROP FUNCTION IF EXISTS fn_organization_effective_rate(INTEGER[], DATE, INTEGER);

CREATE OR REPLACE FUNCTION fn_organization_effective_rate(
    p_user_id      INTEGER,
    p_property_ids  INTEGER[],
    p_today         DATE,
    p_window_days   INTEGER DEFAULT 30
)
RETURNS NUMERIC
LANGUAGE plpgsql
AS $$
DECLARE
    v_property_ids INTEGER[] := fn_user_authorized_property_ids(p_user_id, p_property_ids);
    v_total_liters NUMERIC;
    v_total_cost   NUMERIC;
BEGIN

    SELECT
          SUM(v.total_liters)
        , SUM(v.cost_value)
      INTO v_total_liters, v_total_cost
      FROM dw.vw_ft_consumption_daily v
     WHERE v.property_id = ANY(v_property_ids)
       AND v.full_date BETWEEN (p_today - (p_window_days - 1)) AND p_today;

    IF v_total_liters IS NULL OR v_total_liters = 0 THEN
        RETURN NULL;
    END IF;

    RETURN v_total_cost / (v_total_liters / 1000);

END;
$$;

CREATE OR REPLACE FUNCTION fn_organization_forecast_context(
    p_user_id          INTEGER,
    p_property_name    TEXT    DEFAULT NULL,
    p_today            DATE    DEFAULT CURRENT_DATE,
    p_history_days     INTEGER DEFAULT 45,
    p_rate_window_days INTEGER DEFAULT 30
)
RETURNS TABLE (
    access_kind           TEXT,
    match_status          TEXT,
    resolved_property_ids INTEGER[],
    candidate_properties  JSON,
    can_estimate          BOOLEAN,
    history               JSON,
    last_bill_month       DATE,
    last_bill_total_value NUMERIC,
    last_bill_m3_value    NUMERIC,
    effective_rate        NUMERIC
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_access_kind           TEXT;
    v_match_status          TEXT;
    v_resolved_property_ids INTEGER[];
    v_candidate_properties  JSON;
    v_can_estimate          BOOLEAN := FALSE;
    v_history               JSON;
    v_last_bill_month       DATE;
    v_last_bill_total_value NUMERIC;
    v_last_bill_m3_value    NUMERIC;
    v_effective_rate        NUMERIC;
    v_match_count           INTEGER;
BEGIN

    v_access_kind := fn_user_access_kind(p_user_id);


    IF v_access_kind <> 'organizational' THEN

        RETURN QUERY
        SELECT
              v_access_kind
            , 'not_applicable'::TEXT
            , NULL::INTEGER[]
            , NULL::JSON
            , FALSE
            , NULL::JSON
            , NULL::DATE
            , NULL::NUMERIC
            , NULL::NUMERIC
            , NULL::NUMERIC;

        RETURN;

    END IF;


    IF p_property_name IS NULL THEN

        v_match_status := 'resolved';

        SELECT array_agg(op.property_id)
          INTO v_resolved_property_ids
          FROM fn_user_organization_properties(p_user_id) op;

    ELSE

        SELECT COUNT(*)
          INTO v_match_count
          FROM fn_user_organization_properties(p_user_id) op
         WHERE op.name ILIKE '%' || p_property_name || '%';

        IF v_match_count = 1 THEN

            v_match_status := 'resolved';

            SELECT array_agg(op.property_id)
              INTO v_resolved_property_ids
              FROM fn_user_organization_properties(p_user_id) op
             WHERE op.name ILIKE '%' || p_property_name || '%';

        ELSIF v_match_count > 1 THEN

            v_match_status := 'ambiguous';

            SELECT json_agg(json_build_object(
                       'property_id', op.property_id,
                       'name', op.name,
                       'city', op.city,
                       'state', op.state
                   ))
              INTO v_candidate_properties
              FROM fn_user_organization_properties(p_user_id) op
             WHERE op.name ILIKE '%' || p_property_name || '%';

        ELSE

            v_match_status := 'not_found';

            SELECT json_agg(json_build_object(
                       'property_id', op.property_id,
                       'name', op.name,
                       'city', op.city,
                       'state', op.state
                   ))
              INTO v_candidate_properties
              FROM fn_user_organization_properties(p_user_id) op;

        END IF;

    END IF;


    IF v_match_status = 'resolved' THEN

        v_can_estimate := fn_organization_can_estimate(p_user_id, v_resolved_property_ids);

        SELECT json_agg(json_build_object(
                   'full_date', h.full_date,
                   'total_liters', h.total_liters
               ) ORDER BY h.full_date)
          INTO v_history
          FROM fn_organization_consumption_history(
                   p_user_id, v_resolved_property_ids, p_history_days, p_today
               ) h;

        SELECT
              b.reference_month
            , b.total_cost
            , b.total_liters / 1000
          INTO
              v_last_bill_month
            , v_last_bill_total_value
            , v_last_bill_m3_value
          FROM fn_organization_last_billed_period(
                   p_user_id, v_resolved_property_ids, p_today
               ) b;

        v_effective_rate := fn_organization_effective_rate(
                                 p_user_id, v_resolved_property_ids, p_today, p_rate_window_days
                             );

    END IF;


    RETURN QUERY
    SELECT
          v_access_kind
        , v_match_status
        , v_resolved_property_ids
        , v_candidate_properties
        , v_can_estimate
        , v_history
        , v_last_bill_month
        , v_last_bill_total_value
        , v_last_bill_m3_value
        , v_effective_rate;

END;
$$;

CREATE OR REPLACE FUNCTION fn_get_user_property_context(
    p_user_id INTEGER
)
RETURNS TABLE (
    region_id         INTEGER,
    classification_id INTEGER
)
LANGUAGE plpgsql
AS $$
BEGIN

    RETURN QUERY
    SELECT
          a.region_id
        , p.classification_id
      FROM tb_user_property up
      JOIN tb_property p
        ON p.id = up.property_id
      JOIN tb_address a
        ON a.id = p.address_id
     WHERE up.user_id = p_user_id
     ORDER BY up.id
     LIMIT 1;

END;
$$;

CREATE OR REPLACE FUNCTION fn_user_forecast_context(
    p_user_id INTEGER,
    p_today   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    can_estimate           BOOLEAN,
    region_id              INTEGER,
    classification_id      INTEGER,
    region_rate            NUMERIC,
    last_bill_month        DATE,
    last_bill_total_value  NUMERIC,
    last_bill_m3_value     NUMERIC
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_can_estimate          BOOLEAN;
    v_region_id             INTEGER;
    v_classification_id     INTEGER;
    v_region_rate           NUMERIC;
    v_last_bill_month       DATE;
    v_last_bill_total_value NUMERIC;
    v_last_bill_m3_value    NUMERIC;
BEGIN

    v_can_estimate := fn_user_can_estimate(p_user_id);


    SELECT c.region_id, c.classification_id
      INTO v_region_id, v_classification_id
      FROM fn_get_user_property_context(p_user_id) c;


    IF v_region_id IS NOT NULL AND v_classification_id IS NOT NULL THEN

        BEGIN
            v_region_rate := fn_get_current_region_rate(
                                  v_region_id, v_classification_id, p_today
                              );
        EXCEPTION
            WHEN OTHERS THEN
                v_region_rate := NULL;
        END;

    END IF;


    SELECT b.month, b.total_value, b.m3_value
      INTO v_last_bill_month, v_last_bill_total_value, v_last_bill_m3_value
      FROM tb_last_water_bill b
     WHERE b.user_id = p_user_id
     ORDER BY b.month DESC
     LIMIT 1;


    RETURN QUERY
    SELECT
          v_can_estimate
        , v_region_id
        , v_classification_id
        , v_region_rate
        , v_last_bill_month
        , v_last_bill_total_value
        , v_last_bill_m3_value;

END;
$$;

CREATE OR REPLACE FUNCTION fn_user_habits(
    p_user_id INTEGER
)
RETURNS TABLE (
    name             VARCHAR,
    category         VARCHAR,
    frequency        INTEGER,
    days             VARCHAR[],
    start_time       TIME,
    end_time         TIME,
    estimated_liters NUMERIC
)
LANGUAGE plpgsql
AS $$
BEGIN

    RETURN QUERY
    SELECT
          h.name
        , h.category
        , uh.frequency
        , COALESCE(
              array_agg(d.name ORDER BY d.id) FILTER (WHERE d.id IS NOT NULL)
            , ARRAY[]::VARCHAR[]
          )
        , uh.start_time
        , uh.end_time
        , uh.estimated_liters
      FROM tb_user_habit uh
      JOIN tb_habit h
        ON h.id = uh.habit_id
      LEFT JOIN tb_user_habit_day uhd
        ON uhd.user_habit_id = uh.id
      LEFT JOIN tb_day_of_week d
        ON d.id = uhd.day_of_week_id
     WHERE uh.user_id = p_user_id
     GROUP BY uh.id, h.name, h.category
     ORDER BY h.name;

END;
$$;

CREATE OR REPLACE FUNCTION fn_user_habits_by_day(
    p_user_id INTEGER,
    p_day     VARCHAR
)
RETURNS TABLE (
    name             VARCHAR,
    frequency        INTEGER,
    start_time       TIME,
    end_time         TIME,
    estimated_liters NUMERIC
)
LANGUAGE plpgsql
AS $$
BEGIN

    RETURN QUERY
    SELECT
          h.name
        , uh.frequency
        , uh.start_time
        , uh.end_time
        , uh.estimated_liters
      FROM tb_user_habit uh
      JOIN tb_habit h
        ON h.id = uh.habit_id
      JOIN tb_user_habit_day uhd
        ON uhd.user_habit_id = uh.id
      JOIN tb_day_of_week d
        ON d.id = uhd.day_of_week_id
     WHERE uh.user_id = p_user_id
       AND d.name = UPPER(p_day)
     ORDER BY uh.start_time NULLS LAST, h.name;

END;
$$;

CREATE OR REPLACE FUNCTION fn_user_location(
    p_user_id INTEGER
)
RETURNS TABLE (
    city  VARCHAR,
    state VARCHAR
)
LANGUAGE plpgsql
AS $$
BEGIN

    RETURN QUERY
    SELECT
          a.city
        , a.state
      FROM tb_user_property up
      JOIN tb_property p
        ON p.id = up.property_id
      JOIN tb_address a
        ON a.id = p.address_id
     WHERE up.user_id = p_user_id
     ORDER BY up.id
     LIMIT 1;

END;
$$;

DROP FUNCTION IF EXISTS fn_create_user_habit(INTEGER, VARCHAR, INTEGER, VARCHAR[]);

CREATE OR REPLACE FUNCTION fn_create_user_habit(
    p_user_id    INTEGER,
    p_habit_name VARCHAR,
    p_frequency  INTEGER,
    p_days       VARCHAR[] DEFAULT ARRAY[]::VARCHAR[],
    p_start_time TIME      DEFAULT NULL,
    p_end_time   TIME      DEFAULT NULL
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_habit_id      INTEGER;
    v_user_habit_id INTEGER;
    v_days_count    INTEGER;
    v_inserted      INTEGER;
BEGIN

    SELECT h.id
      INTO v_habit_id
      FROM tb_habit h
     WHERE h.name = UPPER(p_habit_name);

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Hábito % não existe no catálogo.', p_habit_name;
    END IF;


    -- O mesmo hábito pode ser cadastrado mais de uma vez (horários ou dias diferentes).
    -- Conflito de dia + horário é barrado pela trigger trg_check_user_habit_day_conflict.
    INSERT INTO tb_user_habit (user_id, habit_id, frequency, start_time, end_time)
    VALUES (p_user_id, v_habit_id, p_frequency, p_start_time, p_end_time)
    RETURNING id INTO v_user_habit_id;


    SELECT COUNT(DISTINCT UPPER(x))
      INTO v_days_count
      FROM unnest(p_days) AS x;

    INSERT INTO tb_user_habit_day (user_habit_id, day_of_week_id)
    SELECT v_user_habit_id, d.id
      FROM tb_day_of_week d
     WHERE d.name IN (SELECT UPPER(x) FROM unnest(p_days) AS x);

    GET DIAGNOSTICS v_inserted = ROW_COUNT;

    IF v_inserted <> v_days_count THEN
        RAISE EXCEPTION 'Dia da semana inválido em %.', p_days;
    END IF;


    RETURN v_user_habit_id;

END;
$$;

-- Regra: o mesmo usuário não pode ter o mesmo hábito, no mesmo dia da semana,
-- com o mesmo horário de início (NULL conta como "sem horário", igual a outro NULL).

-- Dispara ao inserir/alterar um dia em tb_user_habit_day.
CREATE OR REPLACE FUNCTION fn_check_user_habit_day_conflict()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN

    IF EXISTS (
        SELECT 1
          FROM tb_user_habit me
          JOIN tb_user_habit other
            ON other.user_id = me.user_id
           AND other.habit_id = me.habit_id
           AND other.id <> me.id
           AND other.start_time IS NOT DISTINCT FROM me.start_time
          JOIN tb_user_habit_day other_day
            ON other_day.user_habit_id = other.id
           AND other_day.day_of_week_id = NEW.day_of_week_id
         WHERE me.id = NEW.user_habit_id
    ) THEN
        RAISE EXCEPTION 'O usuário já possui esse hábito nesse dia e horário.';
    END IF;

    RETURN NEW;

END;
$$;

-- Dispara ao trocar o hábito ou o horário em tb_user_habit (os dias já existem).
CREATE OR REPLACE FUNCTION fn_check_user_habit_conflict()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN

    IF EXISTS (
        SELECT 1
          FROM tb_user_habit other
          JOIN tb_user_habit_day other_day
            ON other_day.user_habit_id = other.id
          JOIN tb_user_habit_day my_day
            ON my_day.user_habit_id = NEW.id
           AND my_day.day_of_week_id = other_day.day_of_week_id
         WHERE other.user_id = NEW.user_id
           AND other.habit_id = NEW.habit_id
           AND other.id <> NEW.id
           AND other.start_time IS NOT DISTINCT FROM NEW.start_time
    ) THEN
        RAISE EXCEPTION 'O usuário já possui esse hábito nesse dia e horário.';
    END IF;

    RETURN NEW;

END;
$$;

CREATE TRIGGER trg_check_user_habit_day_conflict
BEFORE INSERT OR UPDATE
ON tb_user_habit_day
FOR EACH ROW
EXECUTE FUNCTION fn_check_user_habit_day_conflict();

CREATE TRIGGER trg_check_user_habit_conflict
BEFORE UPDATE OF user_id, habit_id, start_time
ON tb_user_habit
FOR EACH ROW
EXECUTE FUNCTION fn_check_user_habit_conflict();

