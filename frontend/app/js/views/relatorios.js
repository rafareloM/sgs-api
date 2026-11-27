import { html, montar } from '../html.js';

// Relatórios (spec 014, R1 a R3; design § Relatórios). Formulário e lista chegam na T2.

export function telaRelatorios(alvo) {
  document.title = 'Relatórios — SGS Recife';
  montar(alvo, html`<div class="page-head"><div><h1>Relatórios</h1>
    <p>Peça um relatório; ele é gerado em segundo plano e fica disponível para baixar até a validade.</p></div></div>
    <div class="empty" data-estado="em-implantacao"><b>Tela em implantação.</b>
    <span>Será entregue na tarefa T2 da spec 014. Nenhum dado é mostrado até lá.</span></div>`);
}
