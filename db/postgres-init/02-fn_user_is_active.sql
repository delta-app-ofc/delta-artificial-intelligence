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