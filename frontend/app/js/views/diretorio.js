import { html, montar } from '../html.js';
import { chamar } from '../api.js';
import { atualizarEnquanto } from '../atualizacao.js';
import { ic } from '../ui/icone.js';
import { carregando, erro, vazio } from '../ui/estado.js';
import { fmtDataHora } from '../ui/format.js';
import { abrirModal, fecharModal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';
import { semAcesso } from './basicas.js';
import { abaGrupos } from './grupos.js';
import { paginacao } from './historico.js';

// Diretório (spec 014, R4.1; design § Diretório): abas por rota, como a ficha da unidade.
// Execuções exige `diretorio:sync`; Grupos, `papel:assign`.

const ABAS = { execucoes: ['Execuções', 'diretorio:sync'], grupos: ['Grupos', 'papel:assign'] };

const TAMANHO = 20;
const SITUACAO = { em_andamento: ['Em andamento', 'wait'], concluida: ['Concluída', 'ok'], falhou: ['Falhou', 'err'] };
const CONFLITO = { email: 'E-mail repetido', username: 'Login repetido' };

const pill = (status) => {
  const [rotulo, classe] = SITUACAO[status] || [status, ''];
  return html`<span class="chip ${classe}" data-ref="situacao" data-status="${status}">${rotulo}</span>`;
};
const porExtenso = (c) => `${c.criados} criados, ${c.atualizados} atualizados, ${c.desativados} desativados`;
const contagens = (c, ref) => html`<span data-ref="${ref}" title="${porExtenso(c)}">+${c.criados} ~${c.atualizados} −${c.desativados}</span>`;
const quem = (id, perfil) => {
  if (id === null) return 'Automática';
  if (id === perfil.me.id) return 'Você';
  return html`<code title="${id}">${id.slice(0, 8)}</code>`;
};

// Execuções da sincronização LDAP (R4.2 a R4.6; design § Diretório → Execuções).
async function abaExecucoes(corpo, perfil) {
  montar(corpo, html`<div class="list-meta">
      <button class="btn btn-primary btn-sm" type="button" id="dir-sincronizar">${ic('refresh')}Sincronizar agora</button>
      <span><span id="dir-auto" class="muted" aria-live="polite"></span>
      <button class="btn btn-line btn-sm" type="button" id="dir-atualizar">${ic('refresh')}Atualizar</button></span></div>
    <div id="dir-aviso"></div><div id="dir-lista"></div>`);
  const aviso = corpo.querySelector('#dir-aviso');
  const lista = corpo.querySelector('#dir-lista');
  const auto = corpo.querySelector('#dir-auto');
  const botao = corpo.querySelector('#dir-sincronizar');
  let pagina = 1;
  let itens = [];

  const carregar = async (silencioso = false) => {
    if (!silencioso) montar(lista, carregando('Lendo as execuções…'));
    let dados;
    try {
      ({ dados } = await chamar('GET', `/admin/diretorio/execucoes?pagina=${pagina}&tamanho=${TAMANHO}`));
    } catch (falha) {
      montar(lista, erro(falha));
      return;
    }
    itens = dados.itens;
    montar(lista, itens.length ? html`<div class="tbl-wrap"><table data-ref="execucoes">
      <thead><tr><th>Início</th><th>Fim</th><th>Situação</th><th>Usuários</th><th>Grupos</th><th>Conflitos</th><th>Disparada por</th><th></th></tr></thead>
      <tbody>${itens.map((e) => html`<tr data-id="${e.id}">
        <td>${fmtDataHora(e.iniciada_em)}</td><td>${fmtDataHora(e.concluida_em) || '—'}</td><td>${pill(e.status)}</td>
        <td>${contagens(e.usuarios, 'usuarios')}</td><td>${contagens(e.grupos, 'grupos')}</td>
        <td data-ref="conflitos">${e.conflitos.length}</td><td data-ref="disparada-por">${quem(e.disparada_por, perfil)}</td>
        <td><button class="btn btn-line btn-sm" type="button" data-detalhe="${e.id}">Detalhes</button></td></tr>`)}</tbody></table></div>
      ${paginacao(pagina, dados.total)}`
      : html`${vazio('Nenhuma sincronização ainda. Clique em Sincronizar agora.')}${paginacao(pagina, dados.total)}`);
    lista.querySelectorAll('[data-pagina]').forEach((b) => b.addEventListener('click', () => { pagina = Number(b.dataset.pagina); recarregar(); }));
    lista.querySelectorAll('[data-detalhe]').forEach((b) => b.addEventListener('click', () => detalharExecucao(b.dataset.detalhe)));
  };
  // R4.6: atualiza sozinho enquanto houver execução em andamento (D014-1).
  const disparar = atualizarEnquanto({
    alvo: lista,
    pendente: () => itens.some((e) => e.status === 'em_andamento'),
    recarregar: () => carregar(true),
    aoMudar: (ligada) => { auto.textContent = ligada ? 'Atualização automática ligada' : 'Atualização automática desligada'; },
  });
  const recarregar = async () => { await carregar(); disparar(); };

  botao.addEventListener('click', async () => {
    botao.disabled = true;
    montar(aviso, html``);
    try {
      await chamar('POST', '/admin/diretorio/sincronizar');
      toast('ok', 'Sincronização iniciada');
      pagina = 1;
      await recarregar();
    } catch (falha) {
      // R4.3: o 409 é aviso, não erro de tela; o 503 diz que falta o LDAP.
      if (falha.status === 409) toast('wait', 'Já há uma sincronização em andamento.');
      else if (falha.status === 503) montar(aviso, html`<div class="err-summary" role="alert" data-ref="ldap-desligado"><b>${ic('alert')}O LDAP não está configurado neste servidor.</b></div>`);
      else montar(aviso, erro(falha));
    } finally {
      botao.disabled = false;
    }
  });
  corpo.querySelector('#dir-atualizar').addEventListener('click', recarregar);
  await recarregar();
}

// R4.5: contagens por extenso, conflitos (só ids, LGPD) e o erro genérico da API.
async function detalharExecucao(id) {
  const caixa = abrirModal(html`<div class="modal-h"><h2>Execução da sincronização</h2></div><div class="modal-b" id="ex-corpo">${carregando('Lendo a execução…')}</div>
    <div class="modal-f"><button class="btn btn-line" type="button" id="ex-fechar">Fechar</button></div>`, { rotulo: 'Detalhe da execução' });
  caixa.querySelector('#ex-fechar').addEventListener('click', fecharModal);
  const destino = caixa.querySelector('#ex-corpo');
  let e;
  try {
    ({ dados: e } = await chamar('GET', `/admin/diretorio/execucoes/${encodeURIComponent(id)}`));
  } catch (falha) {
    montar(destino, erro(falha));
    return;
  }
  montar(destino, html`${e.erro ? html`<div class="banner wait" data-ref="erro">${ic('alert')}<p>${e.erro}</p></div>` : ''}
    <dl class="kv" data-ref="detalhe-execucao">
      <div><dt>Situação</dt><dd>${pill(e.status)}</dd></div>
      <div><dt>Início</dt><dd>${fmtDataHora(e.iniciada_em)}</dd></div>
      <div><dt>Fim</dt><dd>${fmtDataHora(e.concluida_em) || '—'}</dd></div>
      <div><dt>Usuários</dt><dd data-ref="usuarios">${porExtenso(e.usuarios)}</dd></div>
      <div><dt>Grupos</dt><dd data-ref="grupos">${porExtenso(e.grupos)}</dd></div>
    </dl>
    ${e.conflitos.length ? html`<table data-ref="conflitos"><thead><tr><th>Tipo</th><th>Id externo</th><th>Conta existente</th></tr></thead>
      <tbody>${e.conflitos.map((c) => html`<tr><td>${CONFLITO[c.tipo] || c.tipo}</td><td><code>${c.external_id}</code></td><td><code>${c.usuario_existente_id || '—'}</code></td></tr>`)}</tbody></table>`
      : vazio('Nenhum conflito nesta execução.')}`);
}

export function telaDiretorio(alvo, perfil, params) {
  document.title = 'Diretório — SGS Recife';
  const permitidas = Object.keys(ABAS).filter((a) => perfil.tem(ABAS[a][1]));
  if (params.aba && ABAS[params.aba] && !permitidas.includes(params.aba)) { semAcesso(alvo); return; }
  const aba = permitidas.includes(params.aba) ? params.aba : permitidas[0];
  if (params.aba !== aba) history.replaceState(null, '', `#/diretorio/${aba}`);
  montar(alvo, html`<div class="page-head"><div><h1>Diretório</h1>
    <p>Usuários e grupos espelhados do LDAP e do provedor de identidade.</p></div></div>
    <section class="panel">
      <nav class="tabs" aria-label="Seções do diretório">${permitidas.map((a) => html`<a href="#/diretorio/${a}" class="${a === aba ? 'on' : ''}" ${a === aba ? html`aria-current="page"` : ''} data-aba="${a}">${ABAS[a][0]}</a>`)}</nav>
      <div id="dir-corpo" style="padding:16px"></div>
    </section>`);
  const corpo = document.getElementById('dir-corpo');
  if (aba === 'execucoes') abaExecucoes(corpo, perfil);
  else abaGrupos(corpo, perfil);
}
