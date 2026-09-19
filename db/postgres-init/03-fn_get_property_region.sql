CREATE OR REPLACE FUNCTION fn_get_property_region(
    p_property_id INTEGER
)
RETURNS VARCHAR(20)
LANGUAGE plpgsql
AS $$
DECLARE
    v_region_name VARCHAR(20);
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