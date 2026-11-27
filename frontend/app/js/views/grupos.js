import { html, montar } from '../html.js';

// Aba Grupos do diretório (spec 014, R5; design § Diretório). Grupos e mapeamentos chegam na T5.

export function abaGrupos(corpo) {
  montar(corpo, html`<div class="empty" data-estado="em-implantacao"><b>Aba em implantação.</b>
    <span>Será entregue na tarefa T5 da spec 014. Nenhum dado é mostrado até lá.</span></div>`);
}
