// Atualização automática limitada (spec 014, R2.2, R4.6; D014-1): a cada 3 s, só enquanto
// houver item pendente, por no máximo 2 min desde o último disparo. Sair da tela tira o `alvo`
// do DOM (o shell refaz #view) e o laço para sozinho.

const PASSO = 3000;
const LIMITE = 2 * 60 * 1000;

// Devolve `disparar()`: chame-a depois de cada carga. Um disparo novo recomeça os 2 min e
// substitui o laço anterior. `aoMudar(ligada)` informa se a atualização está ligada.
export function atualizarEnquanto({ alvo, pendente, recarregar, aoMudar = () => {} }) {
  let geracao = 0;
  return function disparar() {
    const minha = ++geracao;
    const fim = Date.now() + LIMITE;
    const passo = async () => {
      const ligada = minha === geracao && alvo.isConnected && pendente() && Date.now() < fim;
      if (minha === geracao) aoMudar(ligada);
      if (!ligada) return;
      setTimeout(async () => {
        if (minha !== geracao || !alvo.isConnected) return;
        try { await recarregar(); } catch { /* a tela mostra o erro; o laço segue */ }
        passo();
      }, PASSO);
    };
    passo();
  };
}
