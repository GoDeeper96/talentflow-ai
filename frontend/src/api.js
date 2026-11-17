// Cliente de la API y autenticación con Cognito (USER_PASSWORD_AUTH, sin librerías).
const CFG = {
  api: import.meta.env.VITE_API_URL,
  region: import.meta.env.VITE_REGION || 'us-east-1',
  clientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
};

const KEY = 'tf_session';

function guardar(s) { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch { /* sin storage */ } }
export function sesion() { try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch { return null; } }
export function logout() { try { sessionStorage.removeItem(KEY); } catch { /* */ } }

async function cognito(target, body) {
  const r = await fetch(`https://cognito-idp.${CFG.region}.amazonaws.com/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}` },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) {
    const msg = d.__type?.includes('NotAuthorized') ? 'Correo o contraseña incorrectos' : (d.message || 'No se pudo iniciar sesión');
    throw new Error(msg);
  }
  return d;
}

export async function login(email, password) {
  const d = await cognito('InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH', ClientId: CFG.clientId, AuthParameters: { USERNAME: email, PASSWORD: password },
  });
  if (!d.AuthenticationResult) throw new Error('Tu usuario requiere un paso adicional; contacta al administrador');
  const a = d.AuthenticationResult;
  const s = { idToken: a.IdToken, refreshToken: a.RefreshToken, exp: Date.now() + a.ExpiresIn * 1000, email };
  guardar(s);
  return s;
}

async function token() {
  const s = sesion();
  if (!s) throw new Error('SESION');
  if (Date.now() < s.exp - 60000) return s.idToken;
  const d = await cognito('InitiateAuth', {
    AuthFlow: 'REFRESH_TOKEN_AUTH', ClientId: CFG.clientId, AuthParameters: { REFRESH_TOKEN: s.refreshToken },
  });
  const a = d.AuthenticationResult;
  guardar({ ...s, idToken: a.IdToken, exp: Date.now() + a.ExpiresIn * 1000 });
  return a.IdToken;
}

export async function api(path, { method = 'GET', body, raw = false } = {}) {
  const t = await token();
  const r = await fetch(CFG.api + path, {
    method,
    headers: { Authorization: `Bearer ${t}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) { logout(); throw new Error('SESION'); }
  if (raw) { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r; }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

export async function subirArchivo(url, file, contentType) {
  const r = await fetch(url, { method: 'PUT', headers: { 'Content-Type': contentType }, body: file });
  if (!r.ok) throw new Error(`No se pudo subir ${file.name}`);
}
