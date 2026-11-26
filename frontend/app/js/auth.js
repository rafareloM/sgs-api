import { chamar, ErroDaApi } from './api.js';

// Sessão (spec 012, R2.1 a R2.6, R2.11). O access token fica só em memória (R2.3, R15.3);
// o refresh é o cookie HttpOnly da API, que o JavaScript não lê.
let token = null;
let renovacaoEmCurso = null;

export const tokenAtual = () => token;
export const temSessao = () => token !== null;

const guardar = (dados) => {
  if (!dados || typeof dados.access_token !== 'string') {
    throw new ErroDaApi(500, { detail: 'Resposta de autenticação inesperada.' });
  }
  token = dados.access_token;
};

export async function entrar(username, password) {
  const { dados } = await chamar('POST', '/auth/login', { corpo: { username, password }, autenticar: false });
  if (dados && dados.access_token) { guardar(dados); return { etapa: 'pronto' }; } // R2.11 (dev)
  if (dados && dados.mfa_enrollment_required) return { etapa: 'cadastrar', mfaToken: dados.mfa_token };
  if (dados && dados.mfa_required) return { etapa: 'verificar', mfaToken: dados.mfa_token };
  throw new ErroDaApi(500, { detail: 'Resposta de login inesperada.' });
}

export async function cadastrarMfa(mfaToken) {
  const { dados } = await chamar('POST', '/auth/mfa/enroll', { corpo: { mfa_token: mfaToken }, autenticar: false });
  return dados.otpauth_uri;
}

export async function confirmarMfa(mfaToken, codigo) {
  const { dados } = await chamar('POST', '/auth/mfa/confirm', { corpo: { mfa_token: mfaToken, code: codigo }, autenticar: false });
  guardar(dados);
}

export async function verificarMfa(mfaToken, codigo) {
  const { dados } = await chamar('POST', '/auth/mfa/verify', { corpo: { mfa_token: mfaToken, code: codigo }, autenticar: false });
  guardar(dados);
}

// Origens de login ligadas na API (spec 004, R3.9). Sem resposta válida, fica só a senha local.
export async function provedores() {
  try {
    const { dados } = await chamar('GET', '/auth/provedores', { autenticar: false });
    return { ldap: dados?.ldap === true, oidc: dados?.oidc === true };
  } catch {
    return { ldap: false, oidc: false };
  }
}

// Refresh silencioso (R2.4); chamadas simultâneas compartilham a mesma renovação.
export function renovar() {
  if (!renovacaoEmCurso) {
    renovacaoEmCurso = chamar('POST', '/auth/refresh', { cabecalhos: { 'X-Requested-With': 'sgs' }, autenticar: false })
      .then(({ dados }) => { guardar(dados); return true; })
      .catch(() => { token = null; return false; })
      .finally(() => { renovacaoEmCurso = null; });
  }
  return renovacaoEmCurso;
}

// Sair (R2.6). O logout da API exige access token válido; se ele expirou (401), a interface
// renova uma única vez pelo refresh e repete o logout uma única vez, sem laço.
// Devolve true quando não resta sessão restaurável: logout aceito, ou refresh recusado com 401
// (refresh inválido ou expirado; a API apaga o cookie). Devolve false quando não deu para
// confirmar (rede, anti-CSRF ou novo 401): o token local é descartado de qualquer forma.
export async function sair() {
  const logout = () => chamar('POST', '/auth/logout', { repetir: false });
  try {
    await logout();
    return true;
  } catch (falha) {
    if (falha.status !== 401) return false;
    try {
      const { dados } = await chamar('POST', '/auth/refresh', {
        cabecalhos: { 'X-Requested-With': 'sgs' }, autenticar: false,
      });
      guardar(dados);
    } catch (falhaDoRefresh) {
      return falhaDoRefresh.status === 401;
    }
    try {
      await logout();
      return true;
    } catch {
      return false;
    }
  } finally {
    token = null;
  }
}

// A chave do autenticador está na própria URI otpauth:// (R2.2).
export function chaveDaUri(uri) {
  try { return new URL(uri).searchParams.get('secret') || ''; } catch { return ''; }
}
