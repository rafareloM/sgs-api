-- Objetivo: dar ao `sgs_owner` só a leitura das tabelas que as funções dele consultam.
-- Justificativa: uma função SECURITY DEFINER enxerga o que o dono enxerga. O trigger do log
--   (011/T7) lê as linhas de unidades, equipamentos e serviços; as funções e views da 0011 cruzam
--   unidades com distritos, tipos, áreas técnicas, trilha de auditoria e usuários. Leitura e
--   nada mais: o `sgs_owner` não altera o cadastro, a trilha nem os usuários (011/R10.2). A única
--   escrita dele é no log do banco, de que é dono (011/T7).
-- Uso: `trg_registry_change_log` e `sp_ensure_monthly_partitions` (011/T7, T8).
-- Requisitos: 011/R10.2
GRANT SELECT ON
    health_units,
    equipments,
    services,
    users,
    audit_log,
    districts,
    unit_types,
    technical_areas
TO sgs_owner;
