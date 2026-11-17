import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { api, login, logout, sesion, subirArchivo } from './api';
import { Histograma, MapaCalor, RankingApilado } from './charts';

const ESTADOS = {
  BORRADOR: ['Rúbrica en borrador', 'gris'], RECIBIENDO_CVS: ['Recibiendo CVs', 'azul'],
  PROCESANDO: ['Procesando', 'ambar'], LISTO: ['Listo para revisión', 'verde'], CERRADO: ['Cerrado', 'gris'],
};
const TIPOS = ['experiencia', 'sector', 'formacion', 'herramientas', 'idiomas', 'certificaciones', 'logros', 'blandas', 'otra'];
const NIVELES_BASE = ['Sin evidencia en el CV', 'Mencionado sin contexto', 'Aplicado en un trabajo o proyecto',
  'Aplicado con responsabilidad clara o continuidad', 'Aplicado con logro cuantificado o certificación con emisor'];

// ---------- Navegación por hash ----------
function useRuta() {
  const [h, setH] = useState(window.location.hash || '#/');
  useEffect(() => { const f = () => setH(window.location.hash || '#/'); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
  return h.replace(/^#/, '').split('/').filter(Boolean);
}
const ir = ruta => { window.location.hash = ruta; };
const fecha = s => (s ? new Date(s.length === 10 ? s + 'T12:00:00' : s).toLocaleDateString('es-PE', { day: '2-digit', month: '2-digit', year: '2-digit' }) : '—');

function Badge({ estado, extra }) {
  const [txt, c] = ESTADOS[estado] || [estado, 'gris'];
  return <span className={`badge ${c}`}>{txt}{extra ? ` ${extra}` : ''}</span>;
}
function Aviso({ msg, tipo = 'error' }) { return msg ? <div className={`aviso ${tipo}`}>{msg}</div> : null; }

// ---------- Login ----------
function Login({ onOk }) {
  const [email, setEmail] = useState(''); const [pass, setPass] = useState('');
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  async function enviar(e) {
    e.preventDefault(); setBusy(true); setErr('');
    try { await login(email.trim(), pass); onOk(); } catch (x) { setErr(x.message); } finally { setBusy(false); }
  }
  return (
    <div className="login">
      <form onSubmit={enviar} className="card">
        <div className="marca">TalentFlow <span>AI</span></div>
        <p className="muted">Evaluación de CVs por rúbrica, con decisión humana.</p>
        <label>Correo<input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus /></label>
        <label>Contraseña<input type="password" value={pass} onChange={e => setPass(e.target.value)} required /></label>
        <Aviso msg={err} />
        <button className="primario" disabled={busy}>{busy ? 'Ingresando…' : 'Ingresar'}</button>
      </form>
    </div>
  );
}

// ---------- Mis procesos ----------
function Procesos({ yo }) {
  const [items, setItems] = useState(null); const [err, setErr] = useState('');
  const [q, setQ] = useState(''); const [estado, setEstado] = useState(''); const [area, setArea] = useState('');
  useEffect(() => { api('/v1/procesos').then(d => setItems(d.items)).catch(e => setErr(e.message)); }, []);
  const areas = useMemo(() => [...new Set((items || []).map(i => i.area).filter(Boolean))], [items]);
  const vista = (items || []).filter(i => (!estado || i.estado === estado) && (!area || i.area === area)
    && (!q || i.titulo.toLowerCase().includes(q.toLowerCase())));
  return (
    <section>
      <div className="titulo-fila">
        <h1>Procesos de selección</h1>
        {yo.rol !== 'lider' && <button className="primario" onClick={() => ir('/nuevo')}>+ Nuevo proceso</button>}
      </div>
      <div className="filtros">
        <input placeholder="Buscar rol…" value={q} onChange={e => setQ(e.target.value)} />
        <select value={estado} onChange={e => setEstado(e.target.value)}>
          <option value="">Todos los estados</option>
          {Object.entries(ESTADOS).map(([k, [t]]) => <option key={k} value={k}>{t}</option>)}
        </select>
        <select value={area} onChange={e => setArea(e.target.value)}>
          <option value="">Todas las áreas</option>{areas.map(a => <option key={a}>{a}</option>)}
        </select>
      </div>
      <Aviso msg={err} />
      {!items ? <p className="muted">Cargando…</p> : (
        <div className="tabla-scroll card sin-pad">
          <table className="tabla">
            <thead><tr><th>Rol</th><th>Área</th><th>Apertura</th><th>Cierre</th><th className="num">CVs</th><th className="num">≥ umbral</th><th className="num">Mejor nota</th><th>Estado</th></tr></thead>
            <tbody>
              {vista.map(p => (
                <tr key={p.id} className="fila-click" onClick={() => ir(`/p/${p.id}/${p.rubrica_aprobada ? 'dashboard' : 'rubrica'}`)}>
                  <td><b>{p.titulo}</b><div className="muted peq">{p.responsable}</div></td>
                  <td>{p.area || '—'}</td><td>{fecha(p.apertura)}</td><td>{fecha(p.cierre)}</td>
                  <td className="num">{p.cvs_recibidos}</td>
                  <td className="num">{p.cvs_procesados ? p.cvs_sobre_umbral : '—'}</td>
                  <td className="num">{p.mejor_nota != null ? `${p.mejor_nota.toFixed(1)}%` : '—'}</td>
                  <td><Badge estado={p.estado} extra={p.estado === 'PROCESANDO' ? `${p.cvs_procesados}/${p.cvs_recibidos}` : ''} /></td>
                </tr>
              ))}
              {!vista.length && <tr><td colSpan="8" className="muted centro">No hay procesos con esos filtros.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---------- Nuevo proceso ----------
function NuevoProceso() {
  const [f, setF] = useState({ titulo: '', area: '', apertura: new Date().toISOString().slice(0, 10), cierre: '', funciones: '', cv_modelo: '' });
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const set = k => e => setF({ ...f, [k]: e.target.value });
  async function leerModelo(e) {
    const file = e.target.files[0]; if (!file) return;
    if (!/\.(txt|md)$/i.test(file.name)) { setErr('Para el CV modelo pega el texto o sube un .txt/.md'); return; }
    setF({ ...f, cv_modelo: await file.text() });
  }
  async function crear(e) {
    e.preventDefault(); setBusy(true); setErr('');
    try { const p = await api('/v1/procesos', { method: 'POST', body: f }); ir(`/p/${p.id}/rubrica`); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  }
  return (
    <section>
      <a className="volver" href="#/">← Procesos</a>
      <h1>Nuevo proceso</h1>
      <form className="card form" onSubmit={crear}>
        <div className="grid2">
          <label>Rol<input value={f.titulo} onChange={set('titulo')} required placeholder="Analista de Datos" /></label>
          <label>Área<input value={f.area} onChange={set('area')} placeholder="BI" /></label>
          <label>Fecha de apertura<input type="date" value={f.apertura} onChange={set('apertura')} /></label>
          <label>Fecha de cierre<input type="date" value={f.cierre} onChange={set('cierre')} /></label>
        </div>
        <label>Funciones del puesto (como en la oferta)
          <textarea rows="7" value={f.funciones} onChange={set('funciones')} required
            placeholder={'- Elaborar dashboards de ventas en Power BI\n- Automatizar reportes con SQL y Python\n- ...'} /></label>
        <label>CV modelo (contexto inicial para proponer métricas)
          <textarea rows="7" value={f.cv_modelo} onChange={set('cv_modelo')} placeholder="Pega aquí el texto del CV de referencia…" /></label>
        <input type="file" accept=".txt,.md" onChange={leerModelo} />
        <p className="muted peq">El CV modelo solo orienta la propuesta de métricas; no se mide el parecido de los postulantes con él.</p>
        <Aviso msg={err} />
        <button className="primario" disabled={busy}>{busy ? 'Creando…' : 'Crear y configurar rúbrica'}</button>
      </form>
    </section>
  );
}

// ---------- Rúbrica ----------
function Likert({ valor, onChange, disabled }) {
  return (
    <div className="likert" role="radiogroup" aria-label="Importancia">
      {[1, 2, 3, 4, 5].map(n => (
        <button type="button" key={n} disabled={disabled} className={valor === n ? 'on' : ''} onClick={() => onChange(n)}
          title={['', 'Poco importante', 'Algo importante', 'Importante', 'Muy importante', 'Crítico'][n]}>{n}</button>
      ))}
    </div>
  );
}

function Rubrica({ proceso, recargar, puedeEditar }) {
  const rub = proceso.rubrica;
  const [metricas, setMetricas] = useState(rub.metricas || []);
  const [umbral, setUmbral] = useState(proceso.umbral);
  const [msg, setMsg] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState('');
  const [abierta, setAbierta] = useState(null);
  const editable = puedeEditar && !rub.aprobada;
  useEffect(() => { setMetricas(rub.metricas || []); }, [rub]);

  const upd = (i, k, v) => setMetricas(ms => ms.map((m, j) => (j === i ? { ...m, [k]: v } : m)));
  const updNivel = (i, n, v) => setMetricas(ms => ms.map((m, j) => (j === i ? { ...m, niveles: m.niveles.map((x, k) => (k === n ? v : x)) } : m)));
  const totalL = metricas.reduce((s, m) => s + (m.importancia || 0), 0) || 1;

  async function accion(nombre, fn) {
    setBusy(nombre); setErr(''); setMsg('');
    try { await fn(); } catch (x) { setErr(x.message); } finally { setBusy(''); }
  }
  const proponer = () => accion('proponer', async () => {
    const d = await api(`/v1/procesos/${proceso.id}/rubrica/proponer`, { method: 'POST' });
    setMetricas(d.metricas); setMsg(`La IA propuso ${d.metricas.length} métricas. Revisa, ajusta la importancia y aprueba.`);
  });
  const guardar = () => accion('guardar', async () => {
    await api(`/v1/procesos/${proceso.id}`, { method: 'PUT', body: { metricas, umbral: Number(umbral) } });
    setMsg('Cambios guardados.'); recargar();
  });
  const aprobar = () => accion('aprobar', async () => {
    await api(`/v1/procesos/${proceso.id}`, { method: 'PUT', body: { metricas, umbral: Number(umbral) } });
    await api(`/v1/procesos/${proceso.id}/rubrica/aprobar`, { method: 'POST' });
    recargar(); ir(`/p/${proceso.id}/cargar`);
  });
  const guardarUmbral = () => accion('umbral', async () => {
    await api(`/v1/procesos/${proceso.id}`, { method: 'PUT', body: { umbral: Number(umbral) } }); setMsg('Umbral actualizado.'); recargar();
  });
  const agregar = () => {
    setMetricas([...metricas, { id: `m${Date.now().toString(36)}`, nombre: '', descripcion: '', tipo: 'otra', importancia: 3, excluyente: false, niveles: [...NIVELES_BASE], origen: 'empresa' }]);
    setAbierta(metricas.length);
  };

  return (
    <div>
      <div className="card info">
        <div><b>Funciones del puesto</b><pre className="pre">{proceso.funciones}</pre></div>
      </div>
      <div className="titulo-fila">
        <h2>Rúbrica {rub.aprobada ? `v${rub.version} · aprobada` : '· borrador'}</h2>
        {editable && <div className="acciones">
          <button onClick={proponer} disabled={!!busy}>{busy === 'proponer' ? 'La IA está proponiendo…' : '✦ Proponer métricas con IA'}</button>
          <button onClick={agregar} disabled={!!busy}>+ Agregar métrica</button>
        </div>}
      </div>
      <p className="muted">La importancia (Likert 1–5) es el peso de cada métrica. El agente asigna a cada postulante un nivel 0–4 con una cita del CV.
        Nota = 100 × Σ(importancia × nivel) ÷ Σ(importancia × 4).</p>
      <Aviso msg={err} /><Aviso msg={msg} tipo="ok" />
      {!metricas.length && <div className="card vacio">Aún no hay métricas. {editable && 'Usa “Proponer métricas con IA” o agrégalas manualmente.'}</div>}
      <div className="metricas">
        {metricas.map((m, i) => (
          <div className="card metrica" key={m.id}>
            <div className="metrica-cab">
              <div className="metrica-nombre">
                {editable ? <input value={m.nombre} placeholder="Nombre de la métrica" onChange={e => upd(i, 'nombre', e.target.value)} /> : <b>{m.nombre}</b>}
                <span className={`chip ${m.origen === 'ia' ? 'ia' : ''}`}>{m.origen === 'ia' ? 'propuesta IA' : 'empresa'}</span>
              </div>
              <div className="metrica-peso">
                <Likert valor={m.importancia} disabled={!editable} onChange={v => upd(i, 'importancia', v)} />
                <span className="muted peq">{((100 * (m.importancia || 0)) / totalL).toFixed(0)}% del total</span>
              </div>
            </div>
            {editable ? <textarea rows="2" value={m.descripcion} placeholder="Qué se mide" onChange={e => upd(i, 'descripcion', e.target.value)} />
              : <p>{m.descripcion}</p>}
            <div className="metrica-pie">
              <select value={m.tipo} disabled={!editable} onChange={e => upd(i, 'tipo', e.target.value)}>{TIPOS.map(t => <option key={t}>{t}</option>)}</select>
              <label className="check"><input type="checkbox" disabled={!editable} checked={!!m.excluyente} onChange={e => upd(i, 'excluyente', e.target.checked)} /> Excluyente (marca revisión, no baja la nota)</label>
              <button className="link" onClick={() => setAbierta(abierta === i ? null : i)}>{abierta === i ? 'Ocultar niveles' : 'Ver niveles 0–4'}</button>
              {editable && <button className="link peligro" onClick={() => setMetricas(metricas.filter((_, j) => j !== i))}>Eliminar</button>}
            </div>
            {abierta === i && <ol start="0" className="niveles">
              {(m.niveles || []).map((n, k) => <li key={k}>{editable ? <input value={n} onChange={e => updNivel(i, k, e.target.value)} /> : n}</li>)}
            </ol>}
          </div>
        ))}
      </div>
      {puedeEditar && <div className="card barra">
        <label className="inline">Umbral del dashboard <input type="number" min="0" max="100" value={umbral} onChange={e => setUmbral(e.target.value)} />%</label>
        {editable ? <div className="acciones">
          <button onClick={guardar} disabled={!!busy}>Guardar borrador</button>
          <button className="primario" onClick={aprobar} disabled={!!busy || metricas.length < 3}>{busy === 'aprobar' ? 'Aprobando…' : 'Aprobar rúbrica'}</button>
        </div> : <button onClick={guardarUmbral} disabled={!!busy}>Guardar umbral</button>}
      </div>}
    </div>
  );
}

// ---------- Cargar CVs ----------
function Cargar({ proceso, recargar }) {
  const [files, setFiles] = useState([]); const [prog, setProg] = useState(null);
  const [err, setErr] = useState(''); const [lotes, setLotes] = useState([]); const [drag, setDrag] = useState(false);
  const cargarLotes = useCallback(() => api(`/v1/procesos/${proceso.id}/lotes`).then(d => setLotes(d.items)).catch(() => {}), [proceso.id]);
  useEffect(() => { cargarLotes(); const t = setInterval(cargarLotes, 5000); return () => clearInterval(t); }, [cargarLotes]);
  if (!proceso.rubrica.aprobada) return <div className="card vacio">Aprueba la rúbrica antes de cargar CVs.</div>;

  const agregar = list => setFiles(prev => [...prev, ...[...list].filter(f => /\.(pdf|txt|md)$/i.test(f.name))]);
  async function subir() {
    setErr(''); setProg({ ok: 0, total: files.length, fallos: [] });
    try {
      const lote = await api(`/v1/procesos/${proceso.id}/lotes`, { method: 'POST', body: { archivos: files.map(f => ({ nombre: f.name, tamano: f.size })) } });
      const porNombre = {}; files.forEach(f => { (porNombre[f.name] ||= []).push(f); });
      const cola = lote.subidas.map(s => ({ ...s, file: porNombre[s.nombre].shift() }));
      const fallos = lote.rechazados.map(r => `${r.nombre}: ${r.motivo}`);
      let ok = 0;
      async function worker() {
        while (cola.length) {
          const s = cola.shift();
          try { await subirArchivo(s.url, s.file, s.content_type); ok += 1; } catch (x) { fallos.push(x.message); }
          setProg({ ok, total: files.length, fallos: [...fallos] });
        }
      }
      await Promise.all([1, 2, 3, 4].map(worker));
      setFiles([]); cargarLotes(); recargar();
    } catch (x) { setErr(x.message); }
  }
  return (
    <div>
      <div className={`card drop ${drag ? 'drag' : ''}`} onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); agregar(e.dataTransfer.files); }}>
        <p><b>Arrastra aquí los CVs</b> (PDF con texto, TXT o MD · hasta 200 por lote · máx. 5 MB c/u)</p>
        <input type="file" multiple accept=".pdf,.txt,.md" onChange={e => agregar(e.target.files)} />
        {files.length > 0 && <>
          <p>{files.length} archivo(s) listos.</p>
          <div className="acciones"><button onClick={() => setFiles([])}>Limpiar</button><button className="primario" onClick={subir}>Subir y evaluar</button></div>
        </>}
        {prog && <div className="prog"><div style={{ width: `${(100 * prog.ok) / Math.max(1, prog.total)}%` }} /><span>Subidos {prog.ok}/{prog.total}</span></div>}
        {prog?.fallos?.length > 0 && <Aviso msg={prog.fallos.join(' · ')} />}
        <Aviso msg={err} />
      </div>
      <h2>Lotes</h2>
      <div className="card sin-pad tabla-scroll">
        <table className="tabla">
          <thead><tr><th>Lote</th><th>Fecha</th><th>Usuario</th><th className="num">Archivos</th><th className="num">En cola / evaluándose</th><th>Avance</th></tr></thead>
          <tbody>{lotes.map(l => (
            <tr key={l.id}><td className="mono">{l.id}</td><td>{new Date(l.creado_en).toLocaleString('es-PE')}</td><td>{l.creado_por}</td>
              <td className="num">{l.total}</td><td className="num">{l.recibidos - l.procesados}</td>
              <td><div className="prog chico"><div style={{ width: `${(100 * l.procesados) / Math.max(1, l.total)}%` }} /><span>{l.procesados}/{l.total}</span></div></td></tr>
          ))}{!lotes.length && <tr><td colSpan="6" className="muted centro">Sin lotes todavía.</td></tr>}</tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Dashboard ----------
function Dashboard({ proceso }) {
  const [todos, setTodos] = useState(null); const [ranking, setRanking] = useState([]); const [err, setErr] = useState('');
  const umbral = proceso.umbral;
  const cargar = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([api(`/v1/procesos/${proceso.id}/postulantes`), api(`/v1/procesos/${proceso.id}/postulantes?min=${umbral}`)]);
      setTodos(a.items); setRanking(b.items);
    } catch (x) { setErr(x.message); }
  }, [proceso.id, umbral]);
  useEffect(() => { cargar(); if (proceso.estado === 'PROCESANDO') { const t = setInterval(cargar, 6000); return () => clearInterval(t); } return undefined; }, [cargar, proceso.estado]);
  if (!todos) return <p className="muted">Cargando…</p>;
  const evaluados = todos.filter(t => t.estado === 'COMPLETADO');
  const notas = evaluados.map(t => t.nota);
  const metricas = proceso.rubrica.metricas || [];
  const abrir = it => ir(`/p/${proceso.id}/c/${it.cv_id}`);
  const kpi = [
    ['Evaluados', evaluados.length], [`≥ ${umbral}%`, ranking.length], ['≥ 75%', evaluados.filter(t => t.nota >= 75).length],
    ['En revisión', todos.filter(t => ['REVISION', 'ERROR'].includes(t.estado) || t.requiere_revision).length],
    ['Nota promedio', notas.length ? `${(notas.reduce((a, b) => a + b, 0) / notas.length).toFixed(1)}%` : '—'],
    ['En proceso', todos.filter(t => ['PROCESANDO', 'PENDIENTE_SUBIDA'].includes(t.estado)).length],
  ];
  return (
    <div>
      <Aviso msg={err} />
      <div className="kpis">{kpi.map(([k, v]) => <div className="card kpi" key={k}><span>{k}</span><b>{v}</b></div>)}</div>
      {!evaluados.length ? <div className="card vacio">Todavía no hay postulantes evaluados. Carga CVs en la pestaña “Cargar CVs”.</div> : <>
        <div className="card"><h3>Distribución de los {evaluados.length} evaluados</h3><Histograma notas={notas} umbral={umbral} /></div>
        <div className="card"><h3>Ranking: postulantes con nota ≥ {umbral}% ({ranking.length})</h3>
          <p className="muted peq">Cada barra se divide según lo que aporta cada métrica. Clic para ver la ficha.</p>
          <RankingApilado items={ranking.slice(0, 40)} metricas={metricas} onSelect={abrir} />
          {ranking.length > 40 && <p className="muted peq">Se muestran los 40 primeros; el resto está en la pestaña Postulantes.</p>}
        </div>
        {ranking.length > 0 && <div className="card"><h3>Nivel por métrica (0–4) de los postulantes ≥ {umbral}%</h3><MapaCalor items={ranking.slice(0, 40)} metricas={metricas} onSelect={abrir} /></div>}
        <p className="muted peq">La nota prioriza la revisión; no es una decisión de contratación. Ningún postulante se descarta automáticamente.</p>
      </>}
    </div>
  );
}

// ---------- Postulantes ----------
function Postulantes({ proceso }) {
  const [items, setItems] = useState(null); const [banda, setBanda] = useState(''); const [estado, setEstado] = useState(''); const [err, setErr] = useState('');
  useEffect(() => { api(`/v1/procesos/${proceso.id}/postulantes`).then(d => setItems(d.items)).catch(e => setErr(e.message)); }, [proceso.id]);
  async function exportar() {
    try {
      const r = await api(`/v1/procesos/${proceso.id}/export`, { raw: true });
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement('a'); a.href = url; a.download = `talentflow_${proceso.titulo.replace(/\W+/g, '_')}.csv`; a.click();
      URL.revokeObjectURL(url);
    } catch (x) { setErr(x.message); }
  }
  if (!items) return <p className="muted">Cargando…</p>;
  const vista = items.filter(i => (!banda || i.banda === banda) && (!estado || i.estado === estado));
  return (
    <div>
      <div className="filtros">
        <select value={banda} onChange={e => setBanda(e.target.value)}><option value="">Todas las bandas</option><option value="ALTA">Alta (≥75%)</option><option value="MEDIA">Media</option><option value="BAJA">Baja</option></select>
        <select value={estado} onChange={e => setEstado(e.target.value)}><option value="">Todos los estados</option>{['COMPLETADO', 'PROCESANDO', 'REVISION', 'ERROR', 'PENDIENTE_SUBIDA'].map(s => <option key={s}>{s}</option>)}</select>
        <button onClick={exportar}>⬇ Exportar CSV</button>
      </div>
      <Aviso msg={err} />
      <div className="card sin-pad tabla-scroll">
        <table className="tabla">
          <thead><tr><th>#</th><th>Postulante</th><th>Archivo</th><th className="num">Nota</th><th>Banda</th><th className="num">Evidencia</th><th>Estado</th><th>Alertas</th></tr></thead>
          <tbody>{vista.map((i, k) => (
            <tr key={i.cv_id} className="fila-click" onClick={() => ir(`/p/${proceso.id}/c/${i.cv_id}`)}>
              <td>{i.nota != null ? k + 1 : '—'}</td><td><b>{i.candidato || '—'}</b><div className="muted peq">{i.titular}</div></td>
              <td className="peq">{i.archivo}</td><td className="num">{i.nota != null ? `${i.nota.toFixed(1)}%` : '—'}</td>
              <td>{i.banda ? <span className={`badge b-${i.banda}`}>{i.banda}</span> : '—'}</td>
              <td className="num">{i.cobertura != null ? `${i.cobertura}%` : '—'}</td>
              <td className="peq">{i.estado}{i.motivo ? <div className="muted">{i.motivo}</div> : null}</td>
              <td>{i.requiere_revision ? <span className="badge ambar">revisión humana</span> : ''}</td>
            </tr>))}
          {!vista.length && <tr><td colSpan="8" className="muted centro">Sin postulantes.</td></tr>}</tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Ficha del postulante ----------
function Ficha({ proceso, cvId }) {
  const [c, setC] = useState(null); const [err, setErr] = useState('');
  useEffect(() => { api(`/v1/procesos/${proceso.id}/postulantes/${cvId}`).then(setC).catch(e => setErr(e.message)); }, [proceso.id, cvId]);
  if (err) return <Aviso msg={err} />;
  if (!c) return <p className="muted">Cargando…</p>;
  const p = c.perfil || {};
  return (
    <div>
      <a className="volver" href={`#/p/${proceso.id}/postulantes`}>← Postulantes</a>
      <div className="card ficha-cab">
        <div><h2>{c.candidato}</h2><div className="muted">{c.titular || c.archivo}</div>
          {p.objetivo && <p className="peq"><b>Objetivo:</b> {p.objetivo}</p>}</div>
        {c.nota != null && <div className="nota-grande"><b>{c.nota.toFixed(1)}%</b><span className={`badge b-${c.banda}`}>{c.banda}</span><span className="muted peq">evidencia en {c.cobertura}% de las métricas</span></div>}
      </div>
      {c.motivo && <Aviso msg={`${c.estado}: ${c.motivo}`} tipo="warn" />}
      {(c.alertas || []).map(a => <Aviso key={a} msg={a} tipo="warn" />)}
      {c.metricas && <div className="card sin-pad tabla-scroll">
        <table className="tabla">
          <thead><tr><th>Métrica</th><th className="num">Importancia</th><th>Nivel</th><th>Estado</th><th>Evidencia en el CV</th></tr></thead>
          <tbody>{c.metricas.map(m => (
            <tr key={m.metrica_id}><td><b>{m.nombre}</b>{m.excluyente && <div className="muted peq">excluyente</div>}</td><td className="num">{m.importancia}</td>
              <td><div className="niveles-bar">{[1, 2, 3, 4].map(n => <i key={n} className={n <= m.nivel ? 'on' : ''} />)}</div><span className="peq">{m.nivel}/4</span></td>
              <td><span className={`badge e-${m.estado.replace(' ', '-')}`}>{m.estado}</span></td>
              <td>{m.cita ? <blockquote>“{m.cita}”</blockquote> : null}<div className="muted peq">{m.justificacion}</div></td></tr>))}
          </tbody>
        </table>
      </div>}
      {c.preguntas?.length > 0 && <div className="card"><h3>Preguntas para validar en la entrevista</h3>
        <ol className="preguntas">{c.preguntas.map((q, i) => <li key={i}><div className="muted peq">Declara: {q.afirmacion}</div>{q.pregunta}</li>)}</ol></div>}
      {p.experiencias?.length > 0 && <div className="card"><h3>Experiencia extraída</h3>
        {p.experiencias.map((x, i) => <div key={i} className="exp"><b>{x.cargo}</b> · {x.empresa} <span className="muted peq">{x.inicio} – {x.fin}</span>
          {x.logros?.length > 0 && <ul>{x.logros.map((l, j) => <li key={j}>{l.descripcion}{l.valor ? <b> ({l.valor})</b> : null}</li>)}</ul>}</div>)}
      </div>}
    </div>
  );
}

// ---------- Proceso ----------
function Proceso({ id, tab, cvId, yo }) {
  const [p, setP] = useState(null); const [err, setErr] = useState('');
  const recargar = useCallback(() => api(`/v1/procesos/${id}`).then(setP).catch(e => setErr(e.message)), [id]);
  useEffect(() => { recargar(); }, [recargar]);
  const timer = useRef();
  useEffect(() => { clearInterval(timer.current); if (p?.estado === 'PROCESANDO') timer.current = setInterval(recargar, 6000); return () => clearInterval(timer.current); }, [p?.estado, recargar]);
  if (err) return <section><a className="volver" href="#/">← Procesos</a><Aviso msg={err} /></section>;
  if (!p) return <p className="muted">Cargando…</p>;
  const puedeEditar = yo.rol !== 'lider';
  const tabs = [['rubrica', 'Rúbrica'], ['cargar', 'Cargar CVs'], ['dashboard', 'Dashboard'], ['postulantes', 'Postulantes']];
  return (
    <section>
      <a className="volver" href="#/">← Procesos</a>
      <div className="titulo-fila">
        <div><h1>{p.titulo}</h1><div className="muted">{p.area} · apertura {fecha(p.apertura)} · cierre {fecha(p.cierre)}</div></div>
        <Badge estado={p.estado} extra={p.estado === 'PROCESANDO' ? `${p.cvs_procesados}/${p.cvs_recibidos}` : ''} />
      </div>
      {cvId ? <Ficha proceso={p} cvId={cvId} /> : <>
        <nav className="tabs">{tabs.map(([k, t]) => <a key={k} href={`#/p/${id}/${k}`} className={tab === k ? 'on' : ''}>{t}</a>)}</nav>
        {tab === 'rubrica' && <Rubrica proceso={p} recargar={recargar} puedeEditar={puedeEditar} />}
        {tab === 'cargar' && (puedeEditar ? <Cargar proceso={p} recargar={recargar} /> : <div className="card vacio">Tu rol solo puede consultar resultados.</div>)}
        {tab === 'dashboard' && <Dashboard proceso={p} />}
        {tab === 'postulantes' && <Postulantes proceso={p} />}
      </>}
    </section>
  );
}

// ---------- App ----------
function App() {
  const [ok, setOk] = useState(!!sesion()); const [yo, setYo] = useState(null);
  const ruta = useRuta();
  useEffect(() => {
    if (!ok) return;
    api('/v1/me').then(setYo).catch(e => { if (e.message === 'SESION') { logout(); setOk(false); } else setYo({ error: e.message }); });
  }, [ok]);
  useEffect(() => {
    const f = e => { if (e.reason?.message === 'SESION') { setOk(false); } };
    window.addEventListener('unhandledrejection', f); return () => window.removeEventListener('unhandledrejection', f);
  }, []);
  if (!ok) return <Login onOk={() => setOk(true)} />;
  if (!yo) return <p className="muted centro pad">Cargando…</p>;
  if (yo.error) return <div className="pad"><Aviso msg={yo.error} /><button onClick={() => { logout(); setOk(false); }}>Salir</button></div>;
  let vista;
  if (ruta[0] === 'nuevo') vista = <NuevoProceso />;
  else if (ruta[0] === 'p' && ruta[1]) vista = <Proceso id={ruta[1]} tab={ruta[2] === 'c' ? null : (ruta[2] || 'dashboard')} cvId={ruta[2] === 'c' ? ruta[3] : null} yo={yo} />;
  else vista = <Procesos yo={yo} />;
  return (
    <>
      <header className="top">
        <a href="#/" className="marca">TalentFlow <span>AI</span></a>
        <div className="empresa">{yo.empresa}</div>
        <div className="usuario"><span>{yo.email} · {yo.rol}{yo.area ? ` (${yo.area})` : ''}</span>
          <button className="link" onClick={() => { logout(); setOk(false); }}>Salir</button></div>
      </header>
      <main>{vista}</main>
    </>
  );
}

createRoot(document.getElementById('root')).render(<App />);
