// Gráficos SVG sin librerías: histograma, ranking apilado y mapa de calor.
export const PALETA = ['#2a6fdb', '#e07b39', '#2fa37a', '#8e5bd0', '#d4a72c', '#d1495b', '#3aa6b9', '#7a8794'];

export function Histograma({ notas, umbral }) {
  const bins = Array.from({ length: 10 }, (_, i) => ({ desde: i * 10, n: 0 }));
  notas.forEach(n => { bins[Math.min(9, Math.floor(n / 10))].n += 1; });
  const max = Math.max(1, ...bins.map(b => b.n));
  const W = 640, H = 200, L = 36, B = 28, T = 12, bw = (W - L - 8) / 10;
  const x = v => L + (v / 100) * (W - L - 8);
  const ticks = [0, Math.ceil(max / 2), max];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Distribución de notas">
      {ticks.map(t => {
        const y = H - B - (t / max) * (H - B - T);
        return <g key={t}><line x1={L} x2={W - 8} y1={y} y2={y} className="grid" /><text x={L - 6} y={y + 4} textAnchor="end" className="tick">{t}</text></g>;
      })}
      {bins.map((b, i) => {
        const h = (b.n / max) * (H - B - T);
        const sobre = b.desde >= umbral;
        return (
          <g key={i}>
            <rect x={L + i * bw + 2} y={H - B - h} width={bw - 4} height={h} rx="3" className={sobre ? 'bar-on' : 'bar-off'}>
              <title>{`${b.desde}–${b.desde + 10}%: ${b.n} postulantes`}</title>
            </rect>
            {b.n > 0 && <text x={L + i * bw + bw / 2} y={H - B - h - 4} textAnchor="middle" className="val">{b.n}</text>}
            <text x={L + i * bw + bw / 2} y={H - 10} textAnchor="middle" className="tick">{b.desde}%</text>
          </g>
        );
      })}
      <line x1={x(umbral)} x2={x(umbral)} y1={T - 4} y2={H - B} className="umbral" />
      <text x={x(umbral) + 4} y={T + 6} className="umbral-txt">umbral {umbral}%</text>
    </svg>
  );
}

export function RankingApilado({ items, metricas, onSelect }) {
  if (!items.length) return <p className="muted">Ningún postulante supera el umbral todavía.</p>;
  const W = 680, rowH = 26, L = 190, R = 52, H = items.length * rowH + 30;
  const x = v => L + (v / 100) * (W - L - R);
  const color = Object.fromEntries(metricas.map((m, i) => [m.id, PALETA[i % PALETA.length]]));
  return (
    <>
      <div className="leyenda">
        {metricas.map(m => <span key={m.id}><i style={{ background: color[m.id] }} />{m.nombre} (L{m.importancia})</span>)}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Ranking de postulantes sobre el umbral">
        {[0, 25, 50, 75, 100].map(t => <g key={t}><line x1={x(t)} x2={x(t)} y1={4} y2={H - 22} className="grid" /><text x={x(t)} y={H - 6} textAnchor="middle" className="tick">{t}%</text></g>)}
        {items.map((it, i) => {
          let acc = 0;
          const y = 6 + i * rowH;
          return (
            <g key={it.cv_id} className="fila-click" onClick={() => onSelect(it)}>
              <text x={L - 8} y={y + 15} textAnchor="end" className="lbl">{`${i + 1}. ${(it.candidato || it.archivo || '').slice(0, 24)}`}</text>
              {(it.metricas || []).map(m => {
                const w = x(acc + m.aporte) - x(acc);
                const el = <rect key={m.metrica_id} x={x(acc)} y={y + 3} width={Math.max(0, w)} height={rowH - 8} fill={color[m.metrica_id] || '#999'}>
                  <title>{`${m.nombre}: nivel ${m.nivel}/4 · aporta ${m.aporte.toFixed(1)} pts`}</title></rect>;
                acc += m.aporte;
                return el;
              })}
              <text x={x(it.nota) + 6} y={y + 15} className="val">{it.nota.toFixed(1)}%</text>
            </g>
          );
        })}
      </svg>
    </>
  );
}

export function MapaCalor({ items, metricas, onSelect }) {
  if (!items.length) return null;
  return (
    <div className="tabla-scroll">
      <table className="heat">
        <thead><tr><th>Postulante</th>{metricas.map(m => <th key={m.id} title={m.descripcion}>{m.nombre}</th>)}<th>Nota</th></tr></thead>
        <tbody>
          {items.map(it => {
            const niv = Object.fromEntries((it.metricas || []).map(m => [m.metrica_id, m]));
            return (
              <tr key={it.cv_id} className="fila-click" onClick={() => onSelect(it)}>
                <td>{it.candidato}</td>
                {metricas.map(m => {
                  const v = niv[m.id]?.nivel ?? 0;
                  return <td key={m.id} className={`n${v}`} title={niv[m.id]?.estado}>{v}</td>;
                })}
                <td><b>{it.nota.toFixed(1)}%</b></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
