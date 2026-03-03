import "./AuthPages.css";

interface Props {
  title: string;
  text: string;
  bullets: string[];
}

export default function AuthHero({ title, text, bullets }: Props) {
  return (
    <aside className="auth-hero" aria-hidden="true">
      <div>
        <p className="auth-hero__eyebrow">TeachersNote</p>
        <h2 className="auth-hero__title">{title}</h2>
        <p className="auth-hero__text">{text}</p>
      </div>
      <ul className="auth-hero__list">
        {bullets.map((item) => (
          <li key={item} className="auth-hero__list-item">
            <span className="auth-hero__dot" />
            {item}
          </li>
        ))}
      </ul>
    </aside>
  );
}
