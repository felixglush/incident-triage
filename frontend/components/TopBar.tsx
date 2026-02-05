export default function TopBar({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="glass card flex flex-wrap items-center justify-between gap-4 p-5">
      <div>
        {subtitle && (
          <p className="text-xs uppercase tracking-[0.2em] text-mist/50">{subtitle}</p>
        )}
        <h2 className="font-display text-2xl text-white">{title}</h2>
      </div>
      {actions && <div className="flex items-center gap-3">{actions}</div>}
    </header>
  );
}
