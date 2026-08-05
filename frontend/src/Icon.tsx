import "material-symbols/outlined.css";

// Material Symbols sind Ligature-Icons (Google-Standard-Ansatz fürs Web) - self-hosted über das
// npm-Paket "material-symbols" statt Google-Fonts-CDN, damit die App ohne externe Netzwerk-
// Abhängigkeit bleibt. .material-symbols-outlined setzt selbst font-size:24px fest - .icon
// überschreibt das bewusst auf "inherit", damit Icons weiterhin einfach über die font-size des
// umgebenden Elements skaliert werden können (genau wie die vorherigen Emoji-Zeichen).
function Icon({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span className={`material-symbols-outlined icon${className ? ` ${className}` : ""}`} aria-hidden="true">
      {name}
    </span>
  );
}

export default Icon;
