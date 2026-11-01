-- Só local: os GRANTs do datamart citam as roles do projeto. O script-roles.sql oficial
-- também cria usuários com senha e usa o banco deltadb, por isso não é copiado aqui.
CREATE ROLE sys_data_engineer;
CREATE ROLE sys_backend_developer;
CREATE ROLE sys_bi_analyst;
CREATE ROLE sys_devops;
CREATE ROLE sys_first_year;
