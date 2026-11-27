import { html, montar } from '../html.js';
import { chamar } from '../api.js';
import { ic } from '../ui/icone.js';
import { carregando, erro, vazio } from '../ui/estado.js';
import { campo, lerFormulario, limparErros, marcarErro, mostrarErros } from '../ui/form.js';
import { fmtData, fmtDataHora } from '../ui/format.js';
import { toast } from '../ui/toast.js';
import { abrirModal, fecharModal } from '../ui/modal.js';
import { carregarReferencia, ROTULO_DO_STATUS } from '../referencias.js';
import { intervaloDoPeriodo } from '../periodo.js';
import { atualizarEnquanto } from '../atualizacao.js';
import { paginacao } from './historico.js';

// Relatórios (spec 014, R1 a R3; design § Relatórios): pedido, lista com atualização limitada,
// download e integridade.

const TAMANHO = 20; // o mesmo de `paginacao` (historico.js)
const TIPOS = { inventario_unidades: 'Inventário de unidades', trilha_auditoria: 'Trilha de auditoria' };
const PERMISSAO_DO_TIPO = { inventario_unidades: 'unidade:read', trilha_auditoria: 'auditoria:read' };
const FORMATOS = { csv: 'CSV', xlsx: 'XLSX' };
const SITUACOES = { pendente: ['wait', 'Pendente'], gerando: ['wait', 'Gerando'], concluido: ['ok', 'Concluído'], falhou: ['err', 'Falhou'] };
const NAO_CONFIGURADA = 'A exportação de relatórios não está configurada neste servidor.';
const REFERENCIAS = { distrito_id: 'distritos', area_tecnica_id: 'areas-tecnicas', tipo_unidade_id: 'tipos-unidade' };

const mensagemDe = (falha) => (falha.status === 503 ? NAO_CONFIGURADA : falha.detail);
const opcoesDe = (mapa) => [...mapa.values()]
  .sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'))
  .map((r) => ({ valor: r.id, rotulo: r.nome }));
const tamanho = (bytes) => {
  if (bytes === null || bytes === undefined) return '—';
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

// Filtros do pedido em texto: nomes das referências no inventário, período e textos na trilha.
function filtrosEmTexto(r, nomes) {
  const f = r.filtros || {};
  const partes = [];
  if (r.tipo === 'trilha_auditoria') {
    // `ate` é exclusivo (meia-noite do dia seguinte): mostra o último dia incluído.
    if (f.de && f.ate) partes.push(`${fmtData(f.de)} a ${fmtData(new Date(new Date(f.ate).getTime() - 1))}`);
    if (f.acao) partes.push(`ação ${f.acao}…`);
    if (f.entidade_tipo) partes.push(`entidade ${f.entidade_tipo}`);
  } else {
    for (const [chave, tipo] of Object.entries(REFERENCIAS)) {
      if (f[chave] !== null && f[chave] !== undefined) partes.push(nomes[tipo].get(String(f[chave]))?.nome || `#${f[chave]}`);
    }
    if (f.status) partes.push(ROTULO_DO_STATUS[f.status] || f.status);
  }
  return partes.length ? partes.join(' · ') : 'sem filtros';
}

const situacao = (r) => {
  const [classe, rotulo] = r.vencido ? ['', 'Vencido'] : (SITUACOES[r.status] || ['', r.status]);
  return html`<span class="chip ${classe}" data-ref="situacao" data-status="${r.status}">${rotulo}</span>`;
};

export async function telaRelatorios(alvo, perfil) {
  document.title = 'Relatórios — SGS Recife';
  const tipos = Object.keys(TIPOS).filter((t) => perfil.tem(PERMISSAO_DO_TIPO[t])); // R1.3
  montar(alvo, carregando());
  let nomes = { distritos: new Map(), 'areas-tecnicas': new Map(), 'tipos-unidade': new Map() };
  if (perfil.tem('unidade:read')) {
    try {
      const mapas = await Promise.all(Object.values(REFERENCIAS).map(carregarReferencia));
      nomes = Object.fromEntries(Object.values(REFERENCIAS).map((t, i) => [t, mapas[i]]));
    } catch (falha) {
      montar(alvo, erro(falha));
      return;
    }
  }
  const tipoInicial = tipos[0];
  montar(alvo, html`<div class="page-head"><div><h1>Relatórios</h1>
    <p>Peça um relatório; ele é gerado em segundo plano e fica disponível para baixar até a validade.</p></div></div>
    <section class="panel">${tipos.length ? html`<form id="relForm" class="panel-b" novalidate aria-label="Pedir relatório">
      <div class="grid g2">
        ${campo({ nome: 'tipo', rotulo: 'Tipo', valor: tipoInicial, obrigatorio: true, opcoes: tipos.map((t) => ({ valor: t, rotulo: TIPOS[t] })) })}
        ${campo({ nome: 'formato', rotulo: 'Formato', valor: 'csv', obrigatorio: true, opcoes: Object.entries(FORMATOS).map(([valor, rotulo]) => ({ valor, rotulo })) })}
      </div>
      <div class="grid g4" data-filtros="inventario_unidades" ${tipoInicial === 'inventario_unidades' ? '' : html`hidden`}>
        ${campo({ nome: 'distrito_id', rotulo: 'Distrito', opcoes: opcoesDe(nomes.distritos), vazio: 'Todos' })}
        ${campo({ nome: 'area_tecnica_id', rotulo: 'Área técnica', opcoes: opcoesDe(nomes['areas-tecnicas']), vazio: 'Todas' })}
        ${campo({ nome: 'tipo_unidade_id', rotulo: 'Tipo de unidade', opcoes: opcoesDe(nomes['tipos-unidade']), vazio: 'Todos' })}
        ${campo({ nome: 'status', rotulo: 'Situação', opcoes: Object.entries(ROTULO_DO_STATUS).map(([valor, rotulo]) => ({ valor, rotulo })), vazio: 'Todas' })}
      </div>
      <div class="grid g4" data-filtros="trilha_auditoria" ${tipoInicial === 'trilha_auditoria' ? '' : html`hidden`}>
        ${campo({ nome: 'de', rotulo: 'De', tipo: 'date', obrigatorio: true })}
        ${campo({ nome: 'ate', rotulo: 'Até (inclusive)', tipo: 'date', obrigatorio: true, ajuda: 'Dias no fuso de Recife. No máximo 366 dias.' })}
        ${campo({ nome: 'acao', rotulo: 'Ação (início)', max: 50, ajuda: 'Ex.: unidade.' })}
        ${campo({ nome: 'entidade_tipo', rotulo: 'Tipo de entidade', max: 50, ajuda: 'Ex.: unidade' })}
      </div>
      <div class="err-summary" id="rel-geral" role="alert" hidden></div>
      <div class="form-actions"><button class="btn btn-primary" type="submit">${ic('send')}Pedir relatório</button></div>
    </form>` : html`<div class="panel-b"><div class="banner info" data-ref="sem-tipo">${ic('info')}<p>Seu perfil não pede nenhum tipo de relatório.</p></div></div>`}</section>
    <section class="panel"><div class="panel-h"><div><h2>Pedidos</h2><p data-ref="auto" aria-live="polite">Atualização automática desligada</p></div>
      <button class="btn btn-line btn-sm" type="button" id="rel-atualizar">${ic('refresh')}Atualizar</button></div>
      <div id="rel-lista">${carregando('Buscando pedidos…')}</div></section>`);

  const lista = document.getElementById('rel-lista');
  const rotuloAuto = alvo.querySelector('[data-ref=auto]');
  let itens = [];
  let pagina = 1;

  const carregar = async (p = pagina) => {
    pagina = p;
    let dados;
    try {
      ({ dados } = await chamar('GET', `/relatorios?pagina=${p}&tamanho=${TAMANHO}`));
    } catch (falha) {
      itens = [];
      montar(lista, erro(falha));
      return;
    }
    itens = dados.itens;
    montar(lista, itens.length ? html`<div class="tbl-wrap"><table data-ref="relatorios">
      <thead><tr><th>Pedido em</th><th>Tipo</th><th>Formato</th><th>Filtros</th><th>Pedido por</th><th>Situação</th><th>Pronto em</th><th>Tamanho</th><th>Validade</th><th>Ações</th></tr></thead>
      <tbody>${itens.map((r) => html`<tr data-id="${r.id}">
        <td>${fmtDataHora(r.criado_em)}</td><td>${TIPOS[r.tipo] || r.tipo}</td><td>${FORMATOS[r.formato] || r.formato}</td>
        <td data-ref="filtros">${filtrosEmTexto(r, nomes)}</td>
        <td>${r.solicitado_por === perfil.me.id ? 'Você' : html`Outro usuário <code title="${r.solicitado_por}">${String(r.solicitado_por).slice(0, 8)}</code>`}</td>
        <td>${situacao(r)}${r.status === 'falhou' && r.erro ? html`<div class="t-sub" data-ref="erro">${r.erro}</div>` : ''}</td>
        <td>${fmtDataHora(r.concluido_em) || '—'}</td><td>${tamanho(r.tamanho_bytes)}</td><td>${fmtDataHora(r.vence_em) || '—'}</td>
        <td><button class="btn btn-line btn-sm" type="button" data-detalhe="${r.id}">Detalhes</button>
          ${r.status === 'concluido' && !r.vencido && perfil.tem('relatorio:download') ? html`<button class="btn btn-primary btn-sm" type="button" data-baixar="${r.id}">${ic('download')}Baixar</button>` : ''}
          ${r.status === 'falhou' && tipos.includes(r.tipo) ? html`<button class="btn btn-line btn-sm" type="button" data-repetir="${r.id}">${ic('refresh')}Pedir de novo</button>` : ''}</td></tr>`)}</tbody></table></div>
      ${paginacao(pagina, dados.total)}` : html`${vazio('Nenhum relatório pedido ainda.')}${pagina > 1 ? paginacao(pagina, dados.total) : ''}`);
    lista.querySelectorAll('[data-pagina]').forEach((b) => b.addEventListener('click', async () => { await carregar(Number(b.dataset.pagina)); disparar(); }));
    lista.querySelectorAll('[data-repetir]').forEach((b) => b.addEventListener('click', () => repetir(b)));
    lista.querySelectorAll('[data-baixar]').forEach((b) => b.addEventListener('click', () => baixar(b)));
    lista.querySelectorAll('[data-detalhe]').forEach((b) => b.addEventListener('click', () => detalhar(b.dataset.detalhe)));
  };

  // R2.2: 3 s, por no máximo 2 min, só com pedido pendente ou gerando; para ao sair da tela.
  const disparar = atualizarEnquanto({
    alvo: lista,
    pendente: () => itens.some((r) => r.status === 'pendente' || r.status === 'gerando'),
    recarregar: () => carregar(),
    aoMudar: (ligada) => { rotuloAuto.textContent = `Atualização automática ${ligada ? 'ligada' : 'desligada'}`; },
  });

  const pedir = async (corpo) => {
    await chamar('POST', '/relatorios', { corpo });
    toast('ok', 'Relatório pedido', 'Ele aparece na lista e é gerado em segundo plano.');
    await carregar(1);
    disparar();
  };

  // R2.5: repete o pedido que falhou com o mesmo tipo, formato e filtros.
  const repetir = async (botao) => {
    const r = itens.find((i) => i.id === botao.dataset.repetir);
    botao.disabled = true;
    try {
      await pedir({ tipo: r.tipo, formato: r.formato, filtros: r.filtros });
    } catch (falha) {
      botao.disabled = false;
      toast('err', 'Não foi possível pedir o relatório', mensagemDe(falha));
    }
  };

  // R2.3, D005-1: a URL pré-assinada é credencial; só vai para a navegação (sem DOM, estado ou log).
  const baixar = async (botao) => {
    botao.disabled = true;
    try {
      const { dados } = await chamar('GET', `/relatorios/${encodeURIComponent(botao.dataset.baixar)}/download`);
      location.assign(dados.url);
    } catch (falha) {
      toast('err', 'Não foi possível baixar o relatório', mensagemDe(falha)); // R2.4: 409, 403, 503
    } finally {
      botao.disabled = false;
    }
  };

  // R3: detalhe sempre lido de novo; em `concluido`, os dados para conferir a assinatura fora daqui.
  const detalhar = async (id) => {
    const caixa = abrirModal(html`<div class="modal-h"><h2>Relatório</h2></div><div class="modal-b" id="rel-det">${carregando('Lendo o pedido…')}</div>
      <div class="modal-f"><button class="btn btn-line" type="button" id="rel-fechar">Fechar</button></div>`, { rotulo: 'Detalhes do relatório' });
    caixa.querySelector('#rel-fechar').addEventListener('click', fecharModal);
    const destino = caixa.querySelector('#rel-det');
    let r;
    try {
      ({ dados: r } = await chamar('GET', `/relatorios/${encodeURIComponent(id)}`));
    } catch (falha) {
      montar(destino, erro(falha));
      return;
    }
    const kv = (rotulo, valor, ref = '') => html`<div><dt>${rotulo}</dt><dd ${ref ? html`data-ref="${ref}"` : ''}>${valor}</dd></div>`;
    const i = r.integridade;
    const json = i ? JSON.stringify(i, null, 2) : '';
    montar(destino, html`<dl class="kv" data-ref="detalhe-relatorio">
      ${kv('Tipo', TIPOS[r.tipo] || r.tipo)}${kv('Formato', FORMATOS[r.formato] || r.formato)}
      ${kv('Filtros', filtrosEmTexto(r, nomes))}${kv('Situação', situacao(r))}
      ${kv('Pedido em', fmtDataHora(r.criado_em))}${kv('Pronto em', fmtDataHora(r.concluido_em) || '—')}
      ${kv('Tamanho', tamanho(r.tamanho_bytes))}${kv('Validade', fmtDataHora(r.vence_em) || '—')}
      ${r.erro ? kv('Erro', r.erro, 'erro') : ''}</dl>
      ${i ? html`<section data-ref="integridade"><h3>Integridade</h3><dl class="kv">
        ${kv('SHA-256', html`<code class="hash">${i.sha256}</code>`, 'sha256')}
        ${kv('Algoritmo', i.algoritmo, 'algoritmo')}
        ${kv('kid', html`<code>${i.kid}</code>`, 'kid')}
        ${kv('Assinatura', html`<code class="hash">${i.assinatura}</code>`, 'assinatura')}</dl>
        <p><button class="btn btn-line btn-sm" type="button" id="rel-copiar">Copiar integridade.json</button></p>
        <pre class="metadados" data-ref="integridade-json" hidden>${json}</pre>
        <p class="hint">Para conferir o arquivo, siga o roteiro <code>docs/operacao/verificar-relatorio.md</code> do repositório.
          <a href="/.well-known/relatorios-jwks.json" target="_blank" rel="noopener">Chaves públicas</a></p></section>` : ''}`);
    const copiar = destino.querySelector('#rel-copiar');
    if (!copiar) return;
    // R3.2: o objeto `integridade` no formato que o roteiro lê; sem clipboard, mostra e seleciona.
    copiar.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(json);
        toast('ok', 'Copiado', 'Salve como integridade.json.');
      } catch {
        const pre = destino.querySelector('[data-ref=integridade-json]');
        pre.hidden = false;
        getSelection().selectAllChildren(pre);
        toast('wait', 'Copie o texto selecionado', 'A área de transferência não está disponível.');
      }
    });
  };

  document.getElementById('rel-atualizar').addEventListener('click', async () => { await carregar(); disparar(); });

  const form = document.getElementById('relForm');
  if (form) {
    const geral = document.getElementById('rel-geral');
    const tipo = form.querySelector('[name=tipo]');
    tipo.addEventListener('change', () => {
      form.querySelectorAll('[data-filtros]').forEach((g) => { g.hidden = g.dataset.filtros !== tipo.value; });
    });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      limparErros(form);
      geral.hidden = true;
      const v = lerFormulario(form);
      if (!v.tipo) { marcarErro(form, 'tipo', 'Escolha o tipo.'); return; }
      if (!v.formato) { marcarErro(form, 'formato', 'Escolha o formato.'); return; }
      const filtros = {};
      if (v.tipo === 'trilha_auditoria') {
        // R1.5: dias de Recife; `ate` vai como a meia-noite seguinte ao dia final (exclusivo).
        const periodo = intervaloDoPeriodo('personalizado', v.de, v.ate);
        if (periodo.erro) { marcarErro(form, 'ate', periodo.erro); return; }
        filtros.de = periodo.de.toISOString();
        filtros.ate = periodo.ate.toISOString();
        if (v.acao) filtros.acao = v.acao;
        if (v.entidade_tipo) filtros.entidade_tipo = v.entidade_tipo;
      } else {
        for (const chave of Object.keys(REFERENCIAS)) if (v[chave]) filtros[chave] = Number(v[chave]);
        if (v.status) filtros.status = v.status;
      }
      const botao = form.querySelector('button[type=submit]');
      botao.disabled = true;
      try {
        await pedir({ tipo: v.tipo, formato: v.formato, filtros });
      } catch (falha) {
        // R1.6: o `campo` da API vem como `trilha_auditoria.filtros.ate`; o da tela é o último segmento.
        const nosCampos = falha.status === 422 && mostrarErros(form, {
          ...falha, errors: falha.errors.map((er) => ({ ...er, campo: String(er.campo).split('.').pop() })),
        });
        if (!nosCampos) {
          geral.hidden = false;
          montar(geral, html`<b>${ic('alert')}${mensagemDe(falha)}</b>`); // R1.7: 503
        }
      } finally {
        botao.disabled = false;
      }
    });
  }

  await carregar(1);
  disparar();
}
