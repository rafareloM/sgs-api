import { html, montar } from '../html.js';
import { ic } from '../ui/icone.js';
import { toast } from '../ui/toast.js';
import { digitos } from '../ui/format.js';
import { entrar, cadastrarMfa, confirmarMfa, verificarMfa, chaveDaUri, provedores } from '../auth.js';

// Login com segundo fator (spec 012, R2.1 a R2.3, R2.7, R2.8, R2.10, R2.11; DF6, DF7).
// Mesma marcação do protótipo; sem contas, senhas ou códigos de demonstração (R2.10).

const lado = html`
    <section class="login-side">
      <div class="stripes" aria-hidden="true"><i style="background:rgba(255,255,255,.1)"></i><i style="background:#006E2B"></i><i style="background:#E94E1B"></i></div>
      <div style="position:relative;display:flex;gap:11px;align-items:center" data-ref="marca">
        <div class="brand-mark" aria-hidden="true"><i style="background:#fff"></i><i style="background:#3FBF6E"></i><i style="background:#FF7A45"></i></div>
        <div><b style="font-size:17px;display:block;line-height:1.1">SGS Recife</b><small style="opacity:.8">Secretaria de Saúde do Recife</small></div>
      </div>
      <div data-ref="apresentacao">
        <h1>Um cadastro só para toda a rede de saúde.</h1>
        <p>As fichas de unidades, serviços e equipamentos que hoje vivem em planilhas, agora em um lugar com regras de validação, aprovação do nível central e histórico de cada alteração.</p>
        <div class="flow" aria-label="Fluxo de valor"><span>Centralizar</span><span>Validar</span><span>Controlar</span><span>Visualizar</span></div>
      </div>
      <small style="opacity:.7;position:relative">Grupo 01 — CESAR School, Projeto 3.</small>
    </section>`;

// Entrada pelo provedor de identidade (spec 004, R3.9): navegação comum até a API, que redireciona.
const entradaOidc = (ligada) => (ligada
  ? html`<a class="btn btn-line" href="/api/v1/auth/oidc/login" style="width:100%;padding:12px;margin-top:16px">Entrar pelo provedor de identidade</a>` : '');

const resumoDeErro = (mensagem) => (mensagem
  ? html`<div class="err-summary" style="margin:0" role="alert"><b>${ic('alert')}${mensagem}</b></div>` : '');

function telaUsuario(estado) {
  return html`
        <h2>Entrar</h2>
        <p class="lead">Use seu usuário e sua senha da Prefeitura.</p>
        <form id="loginForm" novalidate>
          <div class="stack" style="gap:16px">
            ${resumoDeErro(estado.erro)}
            <div class="fld"><label for="lg-user">Usuário</label><input id="lg-user" type="text" autocomplete="username" autocapitalize="none" spellcheck="false" value="${estado.usuario || ''}"></div>
            <div class="fld"><label for="lg-pass">Senha</label><input id="lg-pass" type="password" autocomplete="current-password"></div>
            <button class="btn btn-primary" type="submit" style="width:100%;padding:12px">Continuar</button>
            <button class="btn btn-quiet" type="button" id="lg-forgot" style="align-self:center">Esqueci minha senha</button>
          </div>
        </form>
        <div data-ref="oidc">${entradaOidc(estado.oidc)}</div>`;
}

function telaCadastro(estado) {
  const chave = chaveDaUri(estado.uri);
  return html`
        <button class="btn btn-quiet" type="button" id="lg-back" style="padding-left:0;margin-bottom:12px">${ic('back')} Voltar</button>
        <h2>Configure o segundo fator</h2>
        <p class="lead">No primeiro acesso, cadastre a conta num aplicativo autenticador (por exemplo, FreeOTP, Google Authenticator ou Microsoft Authenticator) e digite o código de 6 dígitos que ele mostrar.</p>
        <form id="codeForm" novalidate>
          <div class="stack" style="gap:16px">
            <div class="fld"><label for="lg-key">Chave para digitar no aplicativo</label>
              <input id="lg-key" type="text" readonly value="${chave}" data-chave>
              <p class="hint">Mostrada só agora. Guarde-a apenas no aplicativo autenticador.</p></div>
            <div class="fld"><label for="lg-uri">Endereço de configuração (otpauth)</label>
              <input id="lg-uri" type="text" readonly value="${estado.uri}"></div>
            ${campoDeCodigo(estado.erro)}
            <button class="btn btn-primary" type="submit" style="width:100%;padding:12px">${ic('lock')} Confirmar e entrar</button>
          </div>
        </form>`;
}

function telaCodigo(estado) {
  return html`
        <button class="btn btn-quiet" type="button" id="lg-back" style="padding-left:0;margin-bottom:12px">${ic('back')} Voltar</button>
        <h2>Confirme que é você</h2>
        <p class="lead">Digite o código de 6 dígitos do seu aplicativo autenticador.</p>
        <form id="codeForm" novalidate>
          <div class="stack" style="gap:16px">
            ${campoDeCodigo(estado.erro)}
            <button class="btn btn-primary" type="submit" style="width:100%;padding:12px">${ic('lock')} Entrar na plataforma</button>
          </div>
        </form>`;
}

const campoDeCodigo = (erro) => html`
            <div class="fld ${erro ? 'bad' : ''}"><label for="lg-code">Código de verificação</label>
              <input id="lg-code" class="code-input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000000" aria-describedby="code-err">
              <p class="fld-err" id="code-err">${erro ? html`${ic('alert')}${erro}` : ''}</p>
            </div>`;

export function mostrarLogin(aoEntrar, estadoInicial = {}) {
  const estado = { etapa: 'usuario', ...estadoInicial };
  document.title = 'Entrar — SGS Recife';

  const desenhar = () => {
    const corpo = estado.etapa === 'usuario' ? telaUsuario(estado)
      : estado.etapa === 'cadastrar' ? telaCadastro(estado) : telaCodigo(estado);
    montar(document.getElementById('app'), html`
  <div class="login">${lado}
    <main class="login-main">
      <div class="login-box">${corpo}
      </div>
    </main>
  </div>`);
    if (estado.etapa === 'usuario') ligarUsuario(); else ligarCodigo();
  };

  const ocupado = (form, sim) => form.querySelectorAll('button, input').forEach((el) => { el.disabled = sim; });

  const ligarUsuario = () => {
    const form = document.getElementById('loginForm');
    document.getElementById('lg-forgot').addEventListener('click', () =>
      toast('ok', 'Redefinição de senha', 'Procure o Administrador de TI da Secretaria para gerar uma nova senha.'));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const usuario = document.getElementById('lg-user').value.trim();
      const senha = document.getElementById('lg-pass').value;
      estado.usuario = usuario;
      if (!usuario || !senha) { estado.erro = 'Preencha usuário e senha.'; desenhar(); return; }
      ocupado(form, true);
      try {
        const r = await entrar(usuario, senha);
        estado.erro = '';
        if (r.etapa === 'pronto') { aoEntrar(); return; }
        estado.mfaToken = r.mfaToken;
        if (r.etapa === 'cadastrar') estado.uri = await cadastrarMfa(r.mfaToken);
        estado.etapa = r.etapa;
      } catch (falha) {
        estado.erro = falha.detail || 'Não foi possível entrar.'; // mensagem da API (R2.7)
      }
      desenhar();
    });
    document.getElementById(estado.usuario ? 'lg-pass' : 'lg-user').focus();
  };

  const ligarCodigo = () => {
    const form = document.getElementById('codeForm');
    const campo = document.getElementById('lg-code');
    document.getElementById('lg-back').addEventListener('click', () => {
      Object.assign(estado, { etapa: 'usuario', erro: '', mfaToken: null, uri: null });
      desenhar();
    });
    campo.addEventListener('input', () => {
      campo.value = digitos(campo.value).slice(0, 6);
      if (campo.value.length === 6) form.requestSubmit();
    });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (campo.value.length !== 6) { estado.erro = 'Digite os 6 dígitos do código.'; desenhar(); return; }
      ocupado(form, true);
      try {
        if (estado.etapa === 'cadastrar') await confirmarMfa(estado.mfaToken, campo.value);
        else await verificarMfa(estado.mfaToken, campo.value);
        aoEntrar();
      } catch (falha) {
        estado.erro = falha.detail || 'Código não confirmado.';
        desenhar();
      }
    });
    campo.focus();
  };

  desenhar();
  // Uma consulta por abertura do login; a entrada aparece sem redesenhar o que já foi digitado.
  provedores().then(({ oidc }) => {
    estado.oidc = oidc;
    const lugar = document.querySelector('.login-box [data-ref=oidc]');
    if (oidc && lugar) montar(lugar, entradaOidc(true));
  });
}
