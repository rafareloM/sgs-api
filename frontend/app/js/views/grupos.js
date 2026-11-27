import { html, montar } from '../html.js';
import { chamar } from '../api.js';
import { buscarTodas } from '../paginas.js';
import { rotuloDoPapel } from '../perms.js';
import { carregando, erro, vazio } from '../ui/estado.js';
import { campo, limparErros, marcarErro, mostrarErros } from '../ui/form.js';
import { ic } from '../ui/icone.js';
import { abrirModal, fecharModal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';
import { paginacao } from './historico.js';

// Aba Grupos do diretório (spec 014, R5; design § Diretório → Grupos): mapeamentos grupo→papel
// e os grupos espelhados. O escopo é digitado como id (D014-2): o Admin TI não lê referências.

const TAMANHO = 20; // o mesmo de `paginacao` (historico.js)
const ORIGENS = { ldap: 'LDAP', oidc: 'OIDC' };
const ESCOPOS = { global: 'Global', distrito: 'Distrito', area: 'Área', unidade: 'Unidade' };
const curto = (id) => `${String(id).slice(0, 8)}…`;
const escopo = (tipo, id) => (tipo === 'global' ? ESCOPOS.global
  : `${ESCOPOS[tipo] || tipo} ${tipo === 'unidade' ? curto(id) : id}`);

export async function abaGrupos(corpo) {
  montar(corpo, html`
    <h2 class="sec-t">Mapeamentos</h2><div id="gm-lista"></div>
    <h2 class="sec-t" style="margin-top:24px">Grupos do diretório</h2>
    <form class="filters" id="fg" role="search" aria-label="Filtros dos grupos">
      <div class="fld grow"><label for="fg-busca">Buscar</label><input id="fg-busca" type="search" maxlength="100" placeholder="Trecho do nome"></div>
      <div class="fld"><label for="fg-origem">Origem</label><select id="fg-origem"><option value="">Todas</option>
        ${Object.entries(ORIGENS).map(([k, r]) => html`<option value="${k}">${r}</option>`)}</select></div>
      <div class="fld"><label for="fg-situacao">Situação</label><select id="fg-situacao">
        <option value="true">Ativos</option><option value="false">Desativados</option></select></div>
    </form>
    <div id="fg-resultado"></div>`);
  const lista = document.getElementById('gm-lista');
  const resultado = document.getElementById('fg-resultado');

  // R5.2: nome do grupo, ativo ou não; sem par, o grupo saiu do espelho.
  const carregarMapeamentos = async () => {
    montar(lista, carregando('Lendo os mapeamentos…'));
    let mapeamentos; let nomes;
    try {
      const [m, ativos, inativos] = await Promise.all([
        chamar('GET', '/admin/mapeamentos-grupo'),
        buscarTodas('/admin/diretorio/grupos', { ativo: true }),
        buscarTodas('/admin/diretorio/grupos', { ativo: false }),
      ]);
      mapeamentos = m.dados;
      nomes = new Map([...ativos.itens, ...inativos.itens].map((g) => [g.id, g.nome]));
    } catch (falha) {
      montar(lista, erro(falha));
      return;
    }
    const nomeDe = (id) => nomes.get(id) || `Grupo removido ${curto(id)}`;
    montar(lista, mapeamentos.length ? html`<div class="tbl-wrap"><table data-ref="mapeamentos">
      <thead><tr><th>Grupo</th><th>Papel</th><th>Escopo</th><th>Ações</th></tr></thead>
      <tbody>${mapeamentos.map((m) => html`<tr data-id="${m.id}"><td>${nomeDe(m.grupo_id)}</td>
        <td>${rotuloDoPapel[m.papel] || m.papel}</td><td>${escopo(m.escopo_tipo, m.escopo_id)}</td>
        <td><button class="btn btn-line btn-sm" type="button" data-remover="${m.id}">${ic('x')}Remover</button></td></tr>`)}</tbody></table></div>`
      : vazio('Nenhum grupo mapeado ainda.'));
    for (const m of mapeamentos) {
      lista.querySelector(`[data-remover="${m.id}"]`).addEventListener('click',
        () => confirmarRemocao(m, nomeDe(m.grupo_id), carregarMapeamentos));
    }
  };

  // R5.1: busca por trecho do nome, origem, situação e paginação.
  const carregarGrupos = async (pagina) => {
    const api = new URLSearchParams([['ativo', document.getElementById('fg-situacao').value],
      ['pagina', String(pagina)], ['tamanho', String(TAMANHO)]]);
    const busca = document.getElementById('fg-busca').value.trim();
    if (busca) api.set('busca', busca);
    const origem = document.getElementById('fg-origem').value;
    if (origem) api.set('origem', origem);
    montar(resultado, carregando('Buscando grupos…'));
    let dados;
    try {
      ({ dados } = await chamar('GET', `/admin/diretorio/grupos?${api}`));
    } catch (falha) {
      montar(resultado, erro(falha));
      return;
    }
    montar(resultado, dados.itens.length ? html`<div class="tbl-wrap"><table data-ref="grupos">
      <thead><tr><th>Nome</th><th>Origem</th><th>Membros ativos</th><th>Situação</th><th>Ações</th></tr></thead>
      <tbody>${dados.itens.map((g) => html`<tr data-id="${g.id}"><td>${g.nome}</td><td>${ORIGENS[g.origem] || g.origem}</td>
        <td>${g.membros_ativos}</td><td><span class="chip ${g.ativo ? 'ok' : 'warn'}">${g.ativo ? 'Ativo' : 'Desativado'}</span></td>
        <td>${g.ativo ? html`<button class="btn btn-line btn-sm" type="button" data-mapear="${g.id}">Mapear</button>` : ''}</td></tr>`)}</tbody></table></div>
      ${paginacao(pagina, dados.total)}` : html`${vazio('Nenhum grupo com estes filtros.')}${paginacao(pagina, dados.total)}`);
    resultado.querySelectorAll('[data-pagina]').forEach((b) => b.addEventListener('click', () => carregarGrupos(Number(b.dataset.pagina))));
    for (const g of dados.itens.filter((x) => x.ativo)) {
      resultado.querySelector(`[data-mapear="${g.id}"]`).addEventListener('click', () => abrirMapear(g, carregarMapeamentos));
    }
  };

  let espera = null;
  document.getElementById('fg').addEventListener('submit', (e) => { e.preventDefault(); carregarGrupos(1); });
  document.getElementById('fg-busca').addEventListener('input', () => {
    clearTimeout(espera);
    espera = setTimeout(() => carregarGrupos(1), 300);
  });
  document.querySelectorAll('#fg select').forEach((s) => s.addEventListener('change', () => carregarGrupos(1)));
  await Promise.all([carregarMapeamentos(), carregarGrupos(1)]);
}

// R5.3, R5.4: o escopo enviado é o exigido pelo papel; 409 e 403 (segregação) ficam no modal.
async function abrirMapear(grupo, recarregar) {
  const caixa = abrirModal(html`<form id="fm" novalidate>
    <div class="modal-h"><h2>Mapear grupo ${grupo.nome}</h2></div>
    <div class="modal-b"><div id="fm-campos">${carregando('Lendo os papéis…')}</div>
      <div class="err-summary" id="fm-geral" role="alert" hidden></div></div>
    <div class="modal-f"><button class="btn btn-line" type="button" id="fm-cancelar">Cancelar</button>
      <button class="btn btn-primary" type="submit" id="fm-enviar" disabled>Mapear</button></div></form>`, { rotulo: `Mapear grupo ${grupo.nome}` });
  caixa.querySelector('#fm-cancelar').addEventListener('click', fecharModal);
  const form = caixa.querySelector('#fm');
  const campos = caixa.querySelector('#fm-campos');
  const geral = caixa.querySelector('#fm-geral');
  const enviar = caixa.querySelector('#fm-enviar');
  let papeis;
  try {
    ({ dados: papeis } = await chamar('GET', '/admin/papeis'));
  } catch (falha) {
    montar(campos, erro(falha));
    return;
  }
  montar(campos, html`${campo({ nome: 'papel', rotulo: 'Papel', obrigatorio: true, opcoes: papeis.map((p) => ({ valor: p.codigo, rotulo: p.nome })) })}
    <p class="hint" data-ref="escopo-exigido" hidden></p>
    <div id="fm-escopo" hidden>${campo({ nome: 'escopo_id', rotulo: 'Id do escopo', obrigatorio: true, max: 36, ajuda: 'Id do distrito ou da área (número) ou da unidade (UUID). A API confere se existe.' })}</div>`);
  enviar.disabled = false;
  const selecionado = () => papeis.find((p) => p.codigo === form.papel.value);
  form.papel.addEventListener('change', () => {
    const p = selecionado();
    const exigido = caixa.querySelector('[data-ref=escopo-exigido]');
    exigido.hidden = !p;
    exigido.textContent = p ? `Escopo exigido: ${ESCOPOS[p.escopo_exigido] || p.escopo_exigido}` : '';
    caixa.querySelector('#fm-escopo').hidden = !p || p.escopo_exigido === 'global';
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    limparErros(form);
    geral.hidden = true;
    const p = selecionado();
    const escopoId = form.escopo_id.value.trim();
    if (!p) { marcarErro(form, 'papel', 'Escolha um papel.'); return; }
    if (p.escopo_exigido !== 'global' && !escopoId) { marcarErro(form, 'escopo_id', 'Informe o id do escopo.'); return; }
    enviar.disabled = true;
    try {
      await chamar('POST', '/admin/mapeamentos-grupo', { corpo: {
        grupo_id: grupo.id, papel: p.codigo, escopo_tipo: p.escopo_exigido,
        escopo_id: p.escopo_exigido === 'global' ? null : escopoId,
      } });
    } catch (falha) {
      enviar.disabled = false;
      if (falha.status === 422 && mostrarErros(form, falha)) return;
      geral.hidden = false;
      montar(geral, html`<b>${ic('alert')}${falha.detail}</b>`);
      return;
    }
    fecharModal();
    toast('ok', 'Grupo mapeado.', 'Os membros ativos recebem o papel na próxima requisição.');
    await recarregar();
  });
}

// R5.5: saem as atribuições derivadas do mapeamento; as diretas ficam.
function confirmarRemocao(mapeamento, nomeDoGrupo, recarregar) {
  const papel = rotuloDoPapel[mapeamento.papel] || mapeamento.papel;
  const caixa = abrirModal(html`<div class="modal-h"><h2>Remover mapeamento</h2></div>
    <div class="modal-b"><p>Remover o mapeamento de ${nomeDoGrupo} para ${papel}? As atribuições que vieram dele saem; as atribuições diretas ficam.</p>
      <p class="fld-err" id="rm-erro" role="alert"></p></div>
    <div class="modal-f"><button class="btn btn-line" type="button" id="rm-cancelar">Cancelar</button>
      <button class="btn btn-danger" type="button" id="rm-confirmar">Remover</button></div>`, { rotulo: 'Remover mapeamento' });
  caixa.querySelector('#rm-cancelar').addEventListener('click', fecharModal);
  const confirmar = caixa.querySelector('#rm-confirmar');
  confirmar.addEventListener('click', async () => {
    confirmar.disabled = true;
    try {
      await chamar('DELETE', `/admin/mapeamentos-grupo/${encodeURIComponent(mapeamento.id)}`);
    } catch (falha) {
      confirmar.disabled = false;
      caixa.querySelector('#rm-erro').textContent = falha.detail;
      return;
    }
    fecharModal();
    toast('ok', 'Mapeamento removido.', 'As atribuições que vieram dele saíram; as diretas ficaram.');
    await recarregar();
  });
}
