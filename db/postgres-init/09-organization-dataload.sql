-- Dataload mínimo pro caminho organizacional: 1 organização, 1 unidade em
-- Lins/SP, usuário 151 (sem tb_user_property) vinculado a ela, e ~14 dias de
-- consumo fabricado direto em gold.ft_consumption_daily (sem stage/silver).

BEGIN;

INSERT INTO tb_organization (corporate_name, trade_name, cnpj, business_segment, declared_unit_count)
VALUES ('ORG TESTE LTDA', 'ORG TESTE', '00000000000191', 'INDUSTRIA', 1);

INSERT INTO tb_address (region_id, cep, city, state)
VALUES (2, '16400000', 'LINS', 'SP');

INSERT INTO tb_property (name, type, classification_id, address_id, organization_id, built_area_m2, registration_date)
VALUES (
    'UNIDADE TESTE ORG LINS',
    'PRÉDIO',
    5, -- COMERCIAL_NORMAL_INDUSTRIAL (ver 06-dataload.sql)
    (SELECT id FROM tb_address WHERE cep = '16400000'),
    (SELECT id FROM tb_organization WHERE cnpj = '00000000000191'),
    800.00,
    CURRENT_DATE
);

INSERT INTO tb_user_organization (user_id, organization_id)
VALUES (151, (SELECT id FROM tb_organization WHERE cnpj = '00000000000191'));

-- Popula gold.dm_date (2024-2028) — idempotente, definido em 08-datamart-schema.sql.
CALL gold.sp_load_dm_date();

INSERT INTO gold.dm_property (property_id, name, property_type, classification_group, city, state, built_area_m2, organization_name, has_operational_profile)
SELECT p.id, p.name, p.type, 'COMERCIAL', a.city, a.state, p.built_area_m2, o.trade_name, FALSE
FROM tb_property p
JOIN tb_address a ON a.id = p.address_id
JOIN tb_organization o ON o.id = p.organization_id
WHERE o.cnpj = '00000000000191';

-- 14 dias de consumo fabricado (litros/dia entre 1200 e 1500, tarifa R$7,20/m³)
-- para a unidade de teste, direto em gold — equivalente ao que a ETL real
-- (bi_etl.py, no delta-database) produziria a partir de telemetria real.
WITH org AS (
    SELECT id FROM tb_organization WHERE cnpj = '00000000000191'
), prop AS (
    SELECT p.id AS property_id FROM tb_property p, org WHERE p.organization_id = org.id
), gp AS (
    SELECT dp.property_key FROM gold.dm_property dp, prop WHERE dp.property_id = prop.property_id
)
INSERT INTO gold.ft_consumption_daily (property_key, date_key, total_liters, avg_flow_lmin, cost_value)
SELECT
      gp.property_key
    , TO_CHAR(sub.d, 'YYYYMMDD')::INTEGER
    , sub.liters
    , 4.5
    , ROUND(sub.liters / 1000.0 * 7.20, 2)
FROM gp
CROSS JOIN LATERAL (
    SELECT d, (1200 + (RANDOM() * 300))::NUMERIC(12,3) AS liters
    FROM generate_series(CURRENT_DATE - INTERVAL '14 days', CURRENT_DATE - INTERVAL '1 day', INTERVAL '1 day') AS d
) sub
ON CONFLICT (property_key, date_key) DO NOTHING;

COMMIT;
