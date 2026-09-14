CREATE OR REPLACE FUNCTION fn_get_property_classification(
    p_property_id INTEGER
)
RETURNS VARCHAR(20)
LANGUAGE plpgsql
AS $$
DECLARE
    v_classification VARCHAR(20);
BEGIN

    SELECT p.classification
      INTO v_classification
      FROM tb_property p
     WHERE p.id = p_property_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Imóvel com id % não encontrado.',
            p_property_id;
    END IF;

    RETURN v_classification;

END;
$$;
