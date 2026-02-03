export default function IncidentHeader() {
  return (
    <header className="border border-mist/10 bg-graphite/30">
      <div className="flex flex-wrap items-center justify-between gap-4 px-4 py-4">
        <div>
          <div className="flex items-center gap-3 text-xs">
            <span className="font-mono text-mist/50">INC-1042</span>
            <span className="text-critical">Critical</span>
            <span className="bg-warning/20 text-warning px-2 py-0.5">Investigating</span>
            <span className="text-mist/50">Platform</span>
            <span className="text-mist/40">Updated 2m ago</span>
          </div>
          <h2 className="text-xl text-white mt-2">
            Database connection pool exhausted
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button className="border border-mist/20 px-4 py-2 text-xs text-mist/70 hover:bg-slate/50 hover:text-white transition-colors">
            Update Status
          </button>
          <button className="bg-critical px-4 py-2 text-xs text-white hover:bg-critical/90 transition-colors">
            Bridge Live
          </button>
        </div>
      </div>
    </header>
  );
}
