import { html, montar } from '../html.js';
import { semAcesso } from './basicas.js';
import { abaGrupos } from './grupos.js';

// Diretório (spec 014, R4.1; design § Diretório): abas por rota, como a ficha da unidade.
// Execuções exige `diretorio:sync`; Grupos, `papel:assign`. Execuções chegam na T4.

const ABAS = { execucoes: ['Execuções', 'diretorio:sync'], grupos: ['Grupos', 'papel:assign'] };

function abaExecucoes(corpo) {
  montar(corpo, html`<div class="empty" data-estado="em-implantacao"><b>Aba em implantação.</b>
    <span>Será entregue na tarefa T4 da spec 014. Nenhum dado é mostrado até lá.</span></div>`);
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
