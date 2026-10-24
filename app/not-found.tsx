import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty">
      <h1 style={{ fontSize: "1.6rem", color: "var(--ink)" }}>Page not found</h1>
      <p>That professor or paper isn&apos;t in the explorer.</p>
      <Link className="btn" href="/">Back to search</Link>
    </div>
  );
}
