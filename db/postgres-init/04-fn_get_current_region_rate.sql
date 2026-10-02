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