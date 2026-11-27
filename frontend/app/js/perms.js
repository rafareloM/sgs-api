// Menu e botões derivados só das permissões efetivas do /me (spec 012, R3.1, R3.2; DF8).
// Esconder um controle não é segurança: a API decide e a interface trata o 403 (R3.4).

const AMPLITUDE = { global: 4, area: 3, distrito: 2, unidade: 1 };

export function criarPerfil(me) {
  const permissoes = me.permissoes || {};
  const escopos = (codigo) => permissoes[codigo] || [];
  const tem = (codigo) => escopos(codigo).length > 0;
  const global = (codigo) => escopos(codigo).some((e) => e.tipo === 'global');
  const maisAmplo = (codigo) => escopos(codigo).reduce((m, e) => Math.max(m, AMPLITUDE[e.tipo] || 0), 0);
  // Atribuição usada no recorte de navegação (R3.5): a primeira em ordem alfabética do papel.
  const atribuicoes = [...(me.papeis || [])].sort((a, b) => a.papel.localeCompare(b.papel));
  const recorte = (tipo) => atribuicoes.find((a) => a.escopo_tipo === tipo) || null;
  // Perfil de unidade: toda permissão de negócio do usuário tem, no máximo, escopo de unidade.
  const negocio = ['unidade:update', 'auditoria:read', 'dashboard:read', 'alteracao:propor'].filter(tem);
  const deUnidade = negocio.length > 0 && negocio.every((c) => maisAmplo(c) === AMPLITUDE.unidade);
  // R6.2: algum escopo da permissão cobre a unidade (global, área do tipo, distrito ou ela mesma)?
  const cobreUnidade = (codigo, { unidadeId, distritoId, areaId }) => escopos(codigo).some((e) => e.tipo === 'global'
    || (e.tipo === 'area' && String(e.id) === String(areaId))
    || (e.tipo === 'distrito' && String(e.id) === String(distritoId))
    || (e.tipo === 'unidade' && String(e.id) === String(unidadeId)));
  return { me, tem, global, escopos, maisAmplo, recorte, deUnidade, cobreUnidade };
}

// Itens do menu: [hash, ícone, rótulo, chave, emDesenvolvimento].
export function itensDoMenu(p) {
  const itens = [];
  const unidadePropria = p.deUnidade ? p.recorte('unidade') : null;
  if (unidadePropria) {
    itens.push([`#/unidade/${encodeURIComponent(unidadePropria.escopo_id)}`, 'home', 'Minha unidade', 'unidade']);
    if (p.tem('alteracao:propor')) itens.push(['#/solicitacoes', 'inbox', 'Minhas solicitações', 'solicitacoes', true]);
    if (p.tem('auditoria:read')) itens.push([`#/unidade/${encodeURIComponent(unidadePropria.escopo_id)}/historico`, 'history', 'Histórico da unidade', 'historico-unidade']);
    return itens;
  }
  if (p.tem('dashboard:read')) itens.push(['#/inicio', 'home', 'Início', 'inicio']);
  if (p.tem('unidade:read')) itens.push(['#/unidades', 'list', 'Unidades', 'unidades']);
  if (p.global('unidade:create')) itens.push(['#/nova', 'plus', 'Cadastrar unidade', 'nova']);
  else if (p.maisAmplo('alteracao:propor') === AMPLITUDE.distrito) itens.push(['#/nova', 'plus', 'Solicitar cadastro', 'nova', true]);
  if (p.tem('alteracao:validar')) itens.push(['#/solicitacoes', 'inbox', 'Validações', 'solicitacoes', true]);
  else if (p.tem('alteracao:propor')) itens.push(['#/solicitacoes', 'inbox', 'Solicitações', 'solicitacoes', true]);
  const blocoDeGestao = [];
  if (p.tem('dashboard:read')) blocoDeGestao.push(['#/qualidade', 'shield', 'Qualidade dos dados', 'qualidade']);
  if (p.tem('auditoria:read')) {
    const auditor = p.global('auditoria:read') && p.tem('auditoria:read_acessos');
    blocoDeGestao.push(['#/historico', 'history', auditor ? 'Histórico geral' : 'Histórico de alterações', 'historico', !p.global('auditoria:read')]);
    if (auditor) blocoDeGestao.push(['#/cadeia', 'shield', 'Verificação da cadeia', 'cadeia']);
  }
  // Spec 014 (R1.1, R4.1): telas da 005 e da 004.
  if (p.tem('relatorio:export')) blocoDeGestao.push(['#/relatorios', 'download', 'Relatórios', 'relatorios']);
  // R16.1: catálogos de tipos, só com regra_validacao:manage global (hoje, o Gestor de Dados).
  if (p.global('regra_validacao:manage')) blocoDeGestao.push(['#/referencias', 'edit', 'Tabelas de referência', 'referencias']);
  if (p.global('unidade:create')) blocoDeGestao.push(['#/importar', 'upload', 'Importar planilha', 'importar', true]);
  if (p.tem('diretorio:sync') || p.tem('papel:assign')) blocoDeGestao.push(['#/diretorio', 'refresh', 'Diretório', 'diretorio']);
  if (p.tem('papel:assign')) blocoDeGestao.push(['#/papeis', 'user', 'Papéis e atribuições', 'papeis']);
  if (p.tem('usuario:manage')) blocoDeGestao.push(['#/usuarios', 'user', 'Usuários', 'usuarios', true]);
  if (itens.length && blocoDeGestao.length) itens.push(['sep']);
  return itens.concat(blocoDeGestao);
}

// Início do perfil (R3.5, R4.1): a ficha própria, o Início ou a primeira tela do menu.
export function inicioDoPerfil(p) {
  const itens = itensDoMenu(p).filter((i) => i[0] !== 'sep');
  if (p.deUnidade) return itens[0] ? itens[0][0] : '#/sem-acesso';
  if (p.tem('dashboard:read')) return '#/inicio';
  const historico = itens.find((i) => i[3] === 'historico');
  return historico ? historico[0] : (itens[0] ? itens[0][0] : '#/sem-acesso');
}

export const rotuloDoPapel = {
  ADMIN_TI: 'Administração de TI',
  GESTOR_DADOS: 'Gestão de dados — nível central',
  COORD_TECNICO: 'Coordenação técnica',
  TECNICO_DISTRITAL: 'Técnico do distrito sanitário',
  GESTOR_UNIDADE: 'Gestão da unidade',
  DIRETORIA: 'Diretoria',
  AUDITOR: 'Auditoria',
};
