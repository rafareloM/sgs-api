-- Consultas de governança da Etapa 03. Parâmetros: :distrito (opcional).

-- consulta: unidades_por_categoria
SELECT
    'status' AS categoria,
    status AS chave,
    COUNT(*) AS total
FROM unidade_saude
WHERE (:distrito IS NULL OR distritosanitario = :distrito)
    AND (:id_unidade IS NULL OR idunidade = :id_unidade)
GROUP BY status
UNION ALL
SELECT
    'tipo' AS categoria,
    tipo AS chave,
    COUNT(*) AS total
FROM unidade_saude
WHERE (:distrito IS NULL OR distritosanitario = :distrito)
    AND (:id_unidade IS NULL OR idunidade = :id_unidade)
GROUP BY tipo
UNION ALL
SELECT
    'distrito' AS categoria,
    distritosanitario AS chave,
    COUNT(*) AS total
FROM unidade_saude
WHERE (:distrito IS NULL OR distritosanitario = :distrito)
    AND (:id_unidade IS NULL OR idunidade = :id_unidade)
GROUP BY distritosanitario
UNION ALL
SELECT 'sem_cnes', 'sem_cnes', COUNT(*)
FROM unidade_saude
WHERE codigocnes IS NULL
    AND (:distrito IS NULL OR distritosanitario = :distrito)
    AND (:id_unidade IS NULL OR idunidade = :id_unidade)
UNION ALL
SELECT 'total', 'geral', COUNT(*)
FROM unidade_saude
WHERE (:distrito IS NULL OR distritosanitario = :distrito)
    AND (:id_unidade IS NULL OR idunidade = :id_unidade);

-- consulta: equipamentos_por_tipo_e_distrito
SELECT
    u.distritosanitario AS distrito,
    e.tipo,
    COUNT(*) AS registros,
    SUM(e.quantidade) AS quantidade
FROM equipamento AS e
JOIN unidade_saude AS u ON u.idunidade = e.idunidade
WHERE (:distrito IS NULL OR u.distritosanitario = :distrito)
    AND (:id_unidade IS NULL OR u.idunidade = :id_unidade)
GROUP BY u.distritosanitario, e.tipo
ORDER BY u.distritosanitario, e.tipo;

-- consulta: alteracoes_por_periodo
SELECT
    COUNT(*) FILTER (
        WHERE a.datahora >= CURRENT_TIMESTAMP - INTERVAL '7 days'
    ) AS ultimos_7_dias,
    COUNT(*) FILTER (
        WHERE a.datahora >= CURRENT_TIMESTAMP - INTERVAL '30 days'
    ) AS ultimos_30_dias
FROM alteracao AS a
JOIN unidade_saude AS u ON u.idunidade = a.idunidade
WHERE (:distrito IS NULL OR u.distritosanitario = :distrito)
    AND (:id_unidade IS NULL OR u.idunidade = :id_unidade);

-- consulta: alteracoes_recentes
SELECT
    a.idalteracao,
    a.datahora,
    a.campoalterado,
    a.valoranterior,
    a.valornovo,
    u.idunidade,
    u.nome AS unidade,
    us.idusuario,
    us.nome AS autor
FROM alteracao AS a
JOIN unidade_saude AS u ON u.idunidade = a.idunidade
JOIN usuario AS us ON us.idusuario = a.idusuario
WHERE (:distrito IS NULL OR u.distritosanitario = :distrito)
    AND (:id_unidade IS NULL OR u.idunidade = :id_unidade)
ORDER BY a.datahora DESC, a.idalteracao DESC
LIMIT 10;