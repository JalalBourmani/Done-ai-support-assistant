import Link from "next/link";

export default function NotFound() {
  return (
    <div className="panel empty" style={{ marginTop: 40 }}>
      <div className="big">Fant ikke siden / saken</div>
      <p className="muted">Saksmappen finnes kanskje ikke i Auto-XSALE.</p>
      <Link href="/" className="btn btn-primary" style={{ marginTop: 14 }}>
        Til oversikten
      </Link>
    </div>
  );
}
