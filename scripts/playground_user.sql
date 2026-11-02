-- Preparação manual do usuário fictício do playground.
-- Execute no mesmo PostgreSQL configurado para a API de IA, antes do MongoDB.
-- Reutiliza o imóvel 178, criado nesta atividade: AGENTE DO FBI DELTA.
-- O hash abaixo vem de uma senha aleatória descartada: não há senha de login
-- fornecida por este script. O playground usa o ID fixo e não exige login.
-- Não altera IDs de usuários antigos, tarifas ou schemas.

BEGIN;

DO $setup$
DECLARE
    v_user_id CONSTANT INTEGER := 123456789;
    v_property_id CONSTANT INTEGER := 178;
    v_device_id CONSTANT TEXT := 'ESP32-TEST-JUIZ-123456789';
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM tb_property p
          JOIN tb_property_classification c ON c.id = p.classification_id
         WHERE p.id = v_property_id
           AND p.name = 'AGENTE DO FBI DELTA'
           AND c.group_name = 'RESIDENCIAL'
           AND p.organization_id IS NULL
    ) THEN
        RAISE EXCEPTION 'O imóvel 178 não corresponde à residência de teste esperada. Nenhuma alteração foi aplicada.';
    END IF;

    IF EXISTS (
        SELECT 1 FROM tb_user_property
         WHERE property_id = v_property_id
           AND user_id NOT IN (12345679, v_user_id)
    ) THEN
        RAISE EXCEPTION 'O imóvel de teste está associado a outro usuário. Confira o vínculo antes de continuar.';
    END IF;

    INSERT INTO tb_user (
        id, name, email, password, birth_date,
        registration_date, is_active, is_admin, is_manager
    )
    VALUES (
        v_user_id,
        'AGENTE DO FBI DELTA',
        'PLAYGROUND.123456789@EXAMPLE.INVALID',
        '$argon2id$v=19$m=19456,t=2,p=1$gIrBuM4ActSHrvTDkon2KA$qE2GkXp/UFPbNW+s/AyWPwrLT6kcjGS4KnmdXpTHhR8',
        DATE '2000-01-01',
        CURRENT_DATE,
        TRUE,
        FALSE,
        FALSE
    )
    ON CONFLICT (id) DO NOTHING;

    IF NOT EXISTS (SELECT 1 FROM tb_user WHERE id = v_user_id AND is_active) THEN
        RAISE EXCEPTION 'O usuário de teste existente está inativo. O script não reativa contas automaticamente.';
    END IF;

    INSERT INTO tb_user_property (user_id, property_id)
    VALUES (v_user_id, v_property_id)
    ON CONFLICT (user_id, property_id) DO NOTHING;

    INSERT INTO tb_device (device_id, property_id, is_active, installation_date)
    VALUES (v_device_id, v_property_id, TRUE, CURRENT_DATE)
    ON CONFLICT (device_id) DO NOTHING;

    IF NOT EXISTS (
        SELECT 1 FROM tb_device
         WHERE device_id = v_device_id AND property_id = v_property_id
    ) THEN
        RAISE EXCEPTION 'O dispositivo de teste já pertence a outro imóvel. O script não altera sua propriedade.';
    END IF;

    UPDATE tb_device
       SET is_active = TRUE
     WHERE device_id = v_device_id
       AND property_id = v_property_id
       AND is_active IS DISTINCT FROM TRUE;
END;
$setup$;

-- Perfil deve ser residential. A elegibilidade também depende da tarifa vigente.
SELECT
    123456789 AS user_id,
    178 AS property_id,
    fn_user_access_kind(123456789) AS access_kind,
    fn_user_can_estimate(123456789) AS can_estimate;

COMMIT;
