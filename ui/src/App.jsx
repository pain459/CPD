import { useCallback, useEffect, useState } from 'react';

const TERMINAL = ['COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED'];
const PALETTE = ['#4a90d9', '#50c878', '#f5a623', '#b07ce8', '#e86a6a', '#38bdf8', '#f472b6'];

/* ---------- theme ---------- */
function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('cpd-theme') || 'light');
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('cpd-theme', theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))];
}

/* ---------- brand ---------- */
function Logo() {
  return (
    <span className="brand">
      <svg viewBox="0 0 44 44" width="36" height="36" aria-hidden="true">
        <defs>
          <linearGradient id="cpd-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4a90d9" />
            <stop offset="1" stopColor="#7b5cd6" />
          </linearGradient>
        </defs>
        <rect x="2" y="2" width="40" height="40" rx="10" fill="url(#cpd-g)" />
        <path d="M10 29V15h9M34 15v14h-9" stroke="#fff" strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="22" cy="22" r="2.6" fill="#fff" />
      </svg>
      <span className="brand-text"><strong>CPD</strong><small>File Drop Portal</small></span>
    </span>
  );
}


function WorldClocks() {
  const [time, setTime] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const formatTime = (timeZone) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(time);

  return (
    <div className="topbar-clocks">
      <span className="clock-item"><span className="clock-label">ET</span> {formatTime("America/New_York")}</span>
      <span className="clock-sep">·</span>
      <span className="clock-item"><span className="clock-label">UTC</span> {formatTime("UTC")}</span>
      <span className="clock-sep">·</span>
      <span className="clock-item"><span className="clock-label">IST</span> {formatTime("Asia/Kolkata")}</span>
    </div>
  );
}

function ThemeToggle({ theme, onToggle }) {
  return (
    <button className="btn ghost" onClick={onToggle} title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}>
      {theme === 'light' ? (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" /></svg>
      ) : (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
      )}
      {theme === 'light' ? 'Dark' : 'Light'}
    </button>
  );
}

/* ---------- charts (dependency-free SVG) ---------- */
function BarsChart({ data }) {
  // data: [{label, value}]
  if (!data.length) return <p className="muted">No data yet.</p>;
  const max = Math.max(...data.map((d) => d.value), 1);
  const W = 560, H = 220, padL = 8, padB = 44, padT = 12;
  const bw = (W - padL * 2) / data.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img">
      {data.map((d, i) => {
        const h = ((H - padB - padT) * d.value) / max;
        const x = padL + i * bw + bw * 0.18;
        return (
          <g key={d.label}>
            <title>{`${d.label}: $${d.value.toLocaleString()}`}</title>
            <rect x={x} y={H - padB - h} width={bw * 0.64} height={h} rx="3" className="bar" />
            {data.length <= 16 && (
              <text x={x + bw * 0.32} y={H - padB + 14} textAnchor="middle" className="axis">
                {d.label.slice(5)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function Donut({ parts, size = 170 }) {
  // parts: [{label, value, color}]
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const R = 54, C = 2 * Math.PI * R;
  let acc = 0;
  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 140 140" width={size} height={size} role="img">
        <circle cx="70" cy="70" r={R} fill="none" strokeWidth="18" className="donut-track" />
        {parts.map((p) => {
          const len = (p.value / total) * C;
          const el = (
            <circle key={p.label} cx="70" cy="70" r={R} fill="none" stroke={p.color}
              strokeWidth="18" strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-acc} transform="rotate(-90 70 70)">
              <title>{`${p.label}: ${p.value.toLocaleString()}`}</title>
            </circle>
          );
          acc += len;
          return el;
        })}
        <text x="70" y="66" textAnchor="middle" className="donut-total">{total.toLocaleString()}</text>
        <text x="70" y="84" textAnchor="middle" className="axis">total</text>
      </svg>
      <ul className="legend">
        {parts.map((p) => (
          <li key={p.label}><i style={{ background: p.color }} />{p.label} — {p.value.toLocaleString()}</li>
        ))}
      </ul>
    </div>
  );
}

/* ---------- job detail (live SSE) ---------- */
function JobDetail({ job, onClose }) {
  const [detail, setDetail] = useState(null);
  const [rows, setRows] = useState([]);
  const [live, setLive] = useState(true);
  useEffect(() => {
    let es;
    let gone = false;
    const fallback = () => {
      fetch(`/api/jobs/${job.id}`)
        .then((x) => {
          if (!x.ok) throw new Error('gone');
          return x.json();
        })
        .then((d) => { setDetail(d); setLive(false); })
        .catch(() => { if (!gone) onClose(); });
    };
    try {
      es = new EventSource(`/api/jobs/${job.id}/events`);
      es.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.error) { es.close(); gone = true; onClose(); return; } // job wiped server-side
        setDetail(d);
        if (TERMINAL.includes(d.status)) {
          es.close();
          setLive(false);
          fetch(`/api/jobs/${job.id}/rows?limit=20`)
            .then((x) => (x.ok ? x.json() : []))
            .then(setRows).catch(() => setRows([]));
        }
      };
      es.onerror = () => { es.close(); fallback(); };
    } catch {
      fallback();
    }
    return () => es && es.close();
  }, [job.id]);
  if (!detail) return <section className="card"><p>Loading job…</p></section>;
  if (!detail.status) {
    return (
      <section className="card">
        <p>This job no longer exists on the server (its data was cleared).</p>
        <button className="btn ghost" onClick={onClose}>Close</button>
      </section>
    );
  }
  const breakdown = Object.entries(detail.error_breakdown || {});
  const maxErr = Math.max(0, ...breakdown.map(([, v]) => v));
  return (
    <section className="card">
      <div className="row-between">
        <h2>{detail.filename}</h2>
        <button className="btn ghost" onClick={onClose}>Close</button>
      </div>
      <p>
        <span className={`pill ${detail.status}`}>{detail.status.replaceAll('_', ' ')}</span>
        {live && <span className="live-dot" title="live updates" />}
        <span className="muted"> {detail.rows_total} total · {detail.rows_ok} loaded · {detail.rows_rejected} quarantined</span>
      </p>
      <p><progress value={detail.progress_pct} max="100" /> {detail.progress_pct}%</p>
      {detail.error_summary && <p className="muted">{detail.error_summary}</p>}
      <p className="downloads">
        <a className="btn" href={`/api/jobs/${job.id}/raw`}>Raw file</a>
        {breakdown.length > 0 && <a className="btn" href={`/api/jobs/${job.id}/errors.csv`}>Quarantine CSV</a>}
      </p>
      {breakdown.length > 0 && (
        <>
          <h3>Quarantine reasons</h3>
          {breakdown.map(([reason, n]) => (
            <div className="bar-row" key={reason}>
              <span className="bar-label">{reason}</span>
              <div className="bar-track"><div className="bar-fill warn" style={{ width: `${(n / maxErr) * 100}%` }} /></div>
              <span className="bar-value">{n}</span>
            </div>
          ))}
        </>
      )}
      {rows.length > 0 && (
        <>
          <h3>Loaded sample (first {rows.length})</h3>
          <div className="table-wrap"><table>
            <thead><tr><th>Order</th><th>Date</th><th>Store</th><th>SKU</th><th>Qty</th><th>Total USD</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.order_id}>
                  <td>{row.order_id}</td><td>{row.order_date}</td><td>{row.store_id}</td>
                  <td>{row.sku}</td><td>{row.qty}</td><td>${row.line_total_usd}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </>
      )}
    </section>
  );
}

/* ---------- uploader: fire-and-forget into server staging ---------- */
/* The whole file streams to the server in one request; the server replies
   with a job id the moment bytes land. From that ack on, refresh is harmless:
   bytes, job row, and progress all live server-side — the file is never
   needed again. */
const LS_SELECTED = 'cpd-selected-job';

function Uploader({ onJob }) {
  const [sending, setSending] = useState(null); // filename in flight
  const [note, setNote] = useState('');
  let picker = null;

  async function send(file) {
    setSending(file.name);
    setNote(`Sending ${file.name} (${(file.size / 1024).toFixed(0)} KB) to server staging…`);
    const fd = new FormData();
    fd.append('file', file);
    let res;
    try {
      res = await fetch('/api/uploads', { method: 'POST', body: fd });
    } catch (e) {
      setSending(null);
      setNote(`Transfer interrupted before the server received the file — please retry. (${e.message})`);
      return;
    }
    setSending(null);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNote(`Upload rejected: ${body.detail || res.status}`);
      return;
    }
    setNote(`Staged as job ${body.job_id.slice(0, 8)}… — safe to refresh, ingestion continues server-side.${body.deduped ? ' (already processed — deduplicated)' : ''}`);
    onJob && onJob(body);
  }

  function onPick(e) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (file) send(file).catch((e) => setNote(`Upload failed: ${e.message}`));
  }

  return (
    <div className="upload">
      <input type="file" accept=".csv,.xlsx,.json" aria-label="Data file"
        ref={(n) => { picker = n; }} onChange={onPick} style={{ display: 'none' }} />
      <div className="row-between">
        <button className="btn primary" disabled={!!sending} onClick={() => picker && picker.click()}>
          {sending ? `Sending ${sending}…` : 'Select file & ingest'}
        </button>
        <span className="muted">CSV · JSON · Excel</span>
      </div>
      {sending && <p><progress /> Transferring bytes to staging…</p>}
      {note && <p className="muted">{note}</p>}
    </div>
  );
}

/* ---------- app ---------- */
export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [jobs, setJobs] = useState([]);
  const [health, setHealth] = useState(null);
  const [summary, setSummary] = useState(null);
  const [selected, setSelectedState] = useState(() => {
    try {
      const id = localStorage.getItem(LS_SELECTED);
      return id ? { id } : null;
    } catch { return null; }
  });
  const [msg, setMsg] = useState('');

  function setSelected(j) {
    setSelectedState(j);
    try {
      if (j) localStorage.setItem(LS_SELECTED, j.id);
      else localStorage.removeItem(LS_SELECTED);
    } catch { /* private mode */ }
  }

  const refresh = useCallback(async () => {
    try {
      const [j, h, s] = await Promise.all([
        fetch('/api/jobs').then((x) => x.json()),
        fetch('/api/health').then((x) => x.json()).catch(() => null),
        fetch('/api/sales/summary').then((x) => x.json()).catch(() => null),
      ]);
      setJobs(j);
      setHealth(h);
      setSummary(s);
    } catch (e) {
      setMsg(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  const scaler = health?.autoscaler;

  async function onJob(done) {
    setSelected({ id: done.job_id });
    refresh();
  }

  const healthy = health?.status === 'ok';
  const statusCounts = {};
  jobs.forEach((j) => { statusCounts[j.status] = (statusCounts[j.status] || 0) + 1; });
  const statusParts = [
    { label: 'Loaded clean', value: statusCounts.COMPLETED || 0, color: '#50c878' },
    { label: 'With quarantine', value: statusCounts.COMPLETED_WITH_ERRORS || 0, color: '#f5a623' },
    { label: 'Failed', value: statusCounts.FAILED || 0, color: '#e86a6a' },
    { label: 'Running', value: jobs.length - (statusCounts.COMPLETED || 0) - (statusCounts.COMPLETED_WITH_ERRORS || 0) - (statusCounts.FAILED || 0), color: '#4a90d9' },
  ].filter((p) => p.value > 0);
  const dayData = (summary?.by_day || []).map((d) => ({ label: d.date, value: Number(d.revenue_usd) }));
  const catParts = (summary?.by_category || []).map((c, i) => ({ label: c.category, value: Number(c.revenue_usd), color: PALETTE[i % PALETTE.length] }));
  const quarantined = jobs.reduce((a, j) => a + j.rows_rejected, 0);

  return (
    <div className="page">
      <header className="topbar">
        <Logo />
        <WorldClocks />
        <div className="topbar-right">
          <span className={`health ${healthy ? 'ok' : 'bad'}`} title={health ? JSON.stringify(health.checks) : 'loading'}>
            {healthy ? 'All systems operational' : 'Checking systems…'}
          </span>
          {scaler && <span className="muted">{scaler.actual} worker{scaler.actual === 1 ? '' : 's'} · queue {scaler.queue}</span>}
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
        </div>
      </header>

      <section className="hero card">
        <div>
          <h1>Client Data Ingestion Portal</h1>
          <p>
            Upload sales files in <strong>CSV, JSON, or Excel</strong> format. CPD validates every row,
            normalizes currencies to USD, loads clean data into the warehouse, and quarantines
            problematic rows with machine-readable reasons. Raw files are archived to S3 object
            storage, and every job can be tracked live below — from upload to loaded.
            Files stream straight into server staging: the instant your upload is
            acknowledged, refresh freely — ingestion continues server-side and the
            file is never needed again.
          </p>
        </div>
        <Uploader onJob={onJob} />
        {msg && <p className="muted">{msg}</p>}
      </section>

      <section className="kpis">
        <div className="card kpi"><small>Orders loaded</small><strong>{(summary?.orders ?? 0).toLocaleString()}</strong></div>
        <div className="card kpi"><small>Revenue (USD)</small><strong>${Number(summary?.revenue_usd ?? 0).toLocaleString()}</strong></div>
        <div className="card kpi"><small>Jobs processed</small><strong>{jobs.length}</strong></div>
        <div className="card kpi"><small>Rows quarantined</small><strong>{quarantined.toLocaleString()}</strong></div>
      </section>

      <section className="grid">
        <div className="card">
          <h2>Revenue by day (USD)</h2>
          <BarsChart data={dayData} />
        </div>
        <div className="card">
          <h2>Revenue share by category</h2>
          {catParts.length ? <Donut parts={catParts} /> : <p className="muted">No data yet.</p>}
        </div>
        <div className="card">
          <h2>Job outcomes</h2>
          {statusParts.length ? <Donut parts={statusParts} /> : <p className="muted">No jobs yet — upload a file to get started.</p>}
        </div>
      </section>

      <section className="card">
        <h2>Ingestion jobs</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>File</th><th>Status</th><th>Progress</th><th>Total / Loaded / Quarantined</th><th>Updated</th></tr></thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} onClick={() => setSelected(j)} className="clickable">
                <td>{j.filename}</td>
                <td><span className={`pill ${j.status}`}>{j.status.replaceAll('_', ' ')}</span></td>
                <td><progress value={j.progress_pct} max="100" /> {j.progress_pct}%</td>
                <td>{j.rows_total} / {j.rows_ok} / {j.rows_rejected}</td>
                <td>{new Date(j.updated_at).toLocaleString()}</td>
              </tr>
            ))}
            {!jobs.length && <tr><td colSpan="5" className="muted">No jobs yet.</td></tr>}
          </tbody>
        </table></div>
      </section>

      {selected && <JobDetail job={selected} onClose={() => setSelected(null)} />}

      <footer className="muted">CPD Data Platform · uploads stage server-side, are deduplicated, archived to S3, and never double-counted.</footer>
    </div>
  );
}
