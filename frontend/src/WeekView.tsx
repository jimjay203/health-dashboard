import WeeklyCalendarWidget from "./WeeklyCalendarWidget";

// Eigene Seite für den Rolling-Horizon-Wochenplan (Diese/Nächste/Übernächste Woche + Wochen bis
// zum nächsten Wettkampf) - vorher Teil der "Heute"-Seite, jetzt ausgelagert.
function WeekView() {
  return (
    <div className="today-view">
      <WeeklyCalendarWidget />
    </div>
  );
}

export default WeekView;
