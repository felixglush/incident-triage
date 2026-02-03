"use client";

// Generate mock data for the last year (52 weeks)
function generateHeatmapData() {
  const data: { date: string; count: number; month: number }[] = [];
  const today = new Date();
  
  for (let i = 364; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    
    // Generate realistic-looking incident counts
    const dayOfWeek = date.getDay();
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    const baseCount = isWeekend ? 1 : 3;
    const variance = Math.floor(Math.random() * 5);
    const spike = Math.random() > 0.9 ? Math.floor(Math.random() * 8) : 0;
    
    data.push({
      date: date.toISOString().split("T")[0],
      count: Math.max(0, baseCount + variance + spike - 2),
      month: date.getMonth(),
    });
  }
  
  return data;
}

const heatmapData = generateHeatmapData();

const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function getIntensityClass(count: number): string {
  if (count === 0) return "bg-slate/30";
  if (count <= 2) return "bg-info/30";
  if (count <= 4) return "bg-info/50";
  if (count <= 6) return "bg-warning/50";
  return "bg-critical/50";
}

export default function IncidentHeatmap() {
  // Group by weeks (columns)
  const weeks: { date: string; count: number; month: number }[][] = [];
  for (let i = 0; i < heatmapData.length; i += 7) {
    weeks.push(heatmapData.slice(i, i + 7));
  }

  // Calculate month labels - show label on first week of each month
  const monthLabels: { weekIndex: number; label: string }[] = [];
  let lastMonth = -1;
  weeks.forEach((week, weekIndex) => {
    // Check if any day in this week starts a new month (day 1)
    const firstDayOfMonth = week.find((day) => {
      const date = new Date(day.date);
      return date.getDate() <= 7 && day.month !== lastMonth;
    });
    if (firstDayOfMonth && firstDayOfMonth.month !== lastMonth) {
      monthLabels.push({
        weekIndex,
        label: monthNames[firstDayOfMonth.month],
      });
      lastMonth = firstDayOfMonth.month;
    }
  });

  const dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  return (
    <div className="border border-mist/10 bg-graphite/30">
      <div className="flex items-center justify-between px-4 py-3 border-b border-mist/10">
        <h3 className="text-sm font-medium text-white">Incident Activity</h3>
        <span className="text-xs text-mist/50">Last year</span>
      </div>
      <div className="p-4">
        {/* Month labels row */}
        <div className="flex mb-3">
          {/* Spacer for day labels column */}
          <div className="w-8 mr-2 flex-shrink-0" />
          {/* Month labels */}
          <div className="flex gap-[2px] relative flex-1">
            {weeks.map((_, weekIndex) => {
              const monthLabel = monthLabels.find((m) => m.weekIndex === weekIndex);
              return (
                <div key={weekIndex} className="flex-1">
                  {monthLabel && (
                    <span className="text-[9px] text-mist/50 absolute whitespace-nowrap">
                      {monthLabel.label}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex gap-[2px]">
          {/* Day labels */}
          <div className="flex flex-col gap-[2px] mr-2 flex-shrink-0">
            {dayLabels.map((day, i) => (
              <div
                key={i}
                className="h-[10px] w-8 text-[9px] text-mist/50 flex items-center"
              >
                {day}
              </div>
            ))}
          </div>
          
          {/* Heatmap grid */}
          <div className="flex flex-1 gap-[2px]">
            {weeks.map((week, weekIndex) => (
              <div key={weekIndex} className="flex flex-col gap-[2px] flex-1">
                {week.map((day) => (
                  <div
                    key={day.date}
                    className={`w-full aspect-square ${getIntensityClass(day.count)} hover:ring-1 hover:ring-white/30 transition-all cursor-default`}
                    title={`${day.date}: ${day.count} incidents`}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
        
        {/* Legend */}
        <div className="flex items-center gap-2 mt-3 text-[10px] text-mist/50">
          <span>Less</span>
          <div className="flex gap-[2px]">
            <div className="h-[12px] w-[12px] bg-slate/30" />
            <div className="h-[12px] w-[12px] bg-info/30" />
            <div className="h-[12px] w-[12px] bg-info/50" />
            <div className="h-[12px] w-[12px] bg-warning/50" />
            <div className="h-[12px] w-[12px] bg-critical/50" />
          </div>
          <span>More</span>
        </div>
      </div>
    </div>
  );
}
